import { get } from 'svelte/store';
import { profile } from '$lib/stores/profile';
import { mode, repoRoot } from '$lib/stores/mode';
import { currentTraceId, isLoading, addMessage, updateLastAssistant } from '$lib/stores/chat';
import { startThinking, updatePhase, stopThinking, updateSseStatus } from '$lib/stores/thinking';
import { connectResearch, disconnectResearch } from '$lib/stores/research';
import { updateTasksFromResponse, clearTasks, updateTask, type CodeTask } from '$lib/stores/tasks';
import { parseBashOutput } from '$lib/stores/terminal';
import { actions, type ActionType } from '$lib/stores/actions';

const API_BASE = '/v1';

function getApiKey(): string {
  try {
    return localStorage.getItem('pandora.apiKey') || 'qwen-local';
  } catch {
    return 'qwen-local';
  }
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

export async function sendMessage(content: string, history: ChatMessage[] = []) {
  const traceId = crypto.randomUUID().slice(0, 16);
  const sessionId = get(profile);
  const currentMode = get(mode);
  const repo = currentMode === 'code' ? get(repoRoot) : undefined;

  // Set loading state
  isLoading.set(true);
  currentTraceId.set(traceId);
  startThinking();
  clearTasks(); // Clear previous tasks when starting new request
  actions.clear(); // Clear previous actions when starting new request

  // Add user message
  addMessage('user', content);

  // Add placeholder for assistant
  addMessage('assistant', '', traceId);

  // Connect research WebSocket
  connectResearch(sessionId);

  // Start thinking SSE
  const thinkingCleanup = connectThinking(traceId);

  try {
    // Use jobs API to avoid 524 timeout on long-running requests
    const payload = {
      messages: [...history, { role: 'user', content }],
      mode: currentMode,
      session_id: sessionId,
      user_id: sessionId,
      repo,
      trace_id: traceId
    };

    // Start the job
    const startResponse = await fetch('/jobs/start', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${getApiKey()}`,
        'X-User-Id': sessionId
      },
      body: JSON.stringify(payload)
    });

    if (!startResponse.ok) {
      throw new Error(`Failed to start job: HTTP ${startResponse.status}`);
    }

    const { job_id } = await startResponse.json();
    console.log('[Chat] Started job:', job_id);

    // Poll for job completion
    const result = await pollJobResult(job_id);
    const assistantContent = result.choices?.[0]?.message?.content || 'No response';
    updateLastAssistant(assistantContent);

    // Update task tracker from response
    // Tasks may be in result directly or in the message content
    updateTasksFromResponse(result);

    // Parse bash output from response (if any tool_outputs present)
    // This handles cases where bash results come in the final response
    if (result.tool_outputs) {
      parseBashOutput(result);
    }

  } catch (error) {
    const errorMsg = error instanceof Error ? error.message : 'Unknown error';
    updateLastAssistant(`Error: ${errorMsg}`);
  } finally {
    thinkingCleanup();
    stopThinking();
    isLoading.set(false);
    currentTraceId.set(null);

    // Disconnect research after a delay
    setTimeout(() => disconnectResearch(), 2000);
  }
}

async function pollJobResult(jobId: string, intervalMs = 2000, maxWaitMs = 600000): Promise<any> {
  const startTime = Date.now();

  while (Date.now() - startTime < maxWaitMs) {
    const response = await fetch(`/jobs/${jobId}`);

    if (!response.ok) {
      throw new Error(`Failed to get job status: HTTP ${response.status}`);
    }

    const job = await response.json();
    console.log('[Chat] Job status:', job.status);

    if (job.status === 'done') {
      return job.result;
    }

    if (job.status === 'error') {
      throw new Error(job.error?.message || 'Job failed');
    }

    if (job.status === 'cancelled') {
      throw new Error('Job was cancelled');
    }

    // Wait before polling again
    await new Promise(resolve => setTimeout(resolve, intervalMs));
  }

  throw new Error('Job timed out after 10 minutes');
}

function connectThinking(traceId: string): () => void {
  console.log('[Thinking] Connecting SSE to', `/v1/thinking/${traceId}`);
  const eventSource = new EventSource(`/v1/thinking/${traceId}`);

  eventSource.onopen = () => {
    console.log('[Thinking] SSE connection opened');
    updateSseStatus('connected');
  };

  // Handle named 'thinking' events from server
  eventSource.addEventListener('thinking', (event: MessageEvent) => {
    console.log('[Thinking] Received event:', event.data);
    try {
      const data = JSON.parse(event.data);
      const { stage, status, confidence, reasoning, duration_ms, details } = data;
      console.log('[Thinking] Parsed:', { stage, status, confidence });

      if (stage) {
        updatePhase(stage, {
          status: status || 'active',
          confidence: confidence || 0,
          reasoning: reasoning || '',
          duration: duration_ms
        });
      }

      // Update task tracker from SSE event details if available
      // Tasks may come during coordinator_planning or orchestrator_executing phases
      if (details) {
        // Check for task_breakdown in details
        if (details.task_breakdown && Array.isArray(details.task_breakdown)) {
          updateTasksFromResponse({ task_breakdown: details.task_breakdown });
        }
        // Check for individual task updates (e.g., tool execution progress)
        if (details.task_id && details.task_status) {
          updateTask(details.task_id, {
            status: details.task_status as CodeTask['status'],
            duration_ms: details.duration_ms
          });
        }
        // Check for tool execution that should update task status
        if (details.tool_name && details.tool_status) {
          // Find task by tool name and update its status
          const toolStatus = details.tool_status;
          const taskStatus: CodeTask['status'] =
            toolStatus === 'complete' ? 'completed' :
            toolStatus === 'running' ? 'in_progress' : 'pending';
          // Note: This updates by tool name match, which may need refinement
          // based on how tasks are actually structured
        }
      }

      // Handle tool_result events for terminal output
      if (stage === 'tool_result' && details) {
        // Parse bash output from the tool result
        // The details contains the tool result with stdout/stderr
        parseBashOutput({
          tool_outputs: [details]
        });
      }

      // If complete event has message, update assistant
      if (stage === 'complete' && data.message) {
        updateLastAssistant(data.message);
      }
    } catch (e) {
      console.error('[Thinking] Parse error:', e);
    }
  });

  // Handle action events for journey log
  eventSource.addEventListener('action', (event: MessageEvent) => {
    console.log('[Thinking] Received action:', event.data);
    try {
      const data = JSON.parse(event.data);
      actions.addAction(
        (data.action_type || 'tool') as ActionType,
        data.label || data.action || 'Unknown action',
        data.detail,
        data.success
      );
    } catch (e) {
      console.error('[Thinking] Action parse error:', e);
    }
  });

  // Also handle keepalive events (optional)
  eventSource.addEventListener('keepalive', () => {
    console.log('[Thinking] Keepalive received');
  });

  eventSource.onerror = (e) => {
    // SSE fires error when connection closes (even normally after complete)
    // Only log as error if we haven't received the complete event
    if (eventSource.readyState === EventSource.CLOSED) {
      console.log('[Thinking] SSE connection closed');
      updateSseStatus('closed');
    } else {
      console.error('[Thinking] SSE error:', e);
      updateSseStatus('error');
    }
    eventSource.close();
  };

  return () => {
    console.log('[Thinking] Closing SSE');
    eventSource.close();
  };
}

export async function cancelRequest(traceId: string) {
  try {
    await fetch(`/v1/thinking/${traceId}/cancel`, { method: 'POST' });
  } catch {}
}
