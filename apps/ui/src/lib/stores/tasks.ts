import { writable } from 'svelte/store';

// Types
export interface CodeTask {
  id: string;
  description: string;
  status: 'pending' | 'in_progress' | 'completed';
  tool?: string;
  files?: string[];
  duration_ms?: number;
  content?: string;
}

// Store
export const tasks = writable<CodeTask[]>([]);

// Actions
export function setTasks(newTasks: CodeTask[]) {
  tasks.set(newTasks);
}

export function addTask(task: CodeTask) {
  tasks.update((t) => [...t, task]);
}

export function updateTask(taskId: string, updates: Partial<CodeTask>) {
  tasks.update((t) =>
    t.map((task) => (task.id === taskId ? { ...task, ...updates } : task))
  );
}

export function clearTasks() {
  tasks.set([]);
}

// Parse task breakdown from LLM response
export function parseTaskBreakdown(responseData: any): CodeTask[] {
  // Try different locations where tasks might be
  let taskData =
    responseData?.reflection?.task_breakdown ||
    responseData?.task_breakdown ||
    responseData?.coordinator?.tasks ||
    null;

  // Try to parse from message content if not found
  // Check both direct message.content and choices[0].message.content (API response format)
  if (!taskData) {
    const content =
      responseData?.message?.content ||
      responseData?.choices?.[0]?.message?.content;

    if (content) {
      // Try to extract JSON block from markdown
      const jsonMatch = content.match(/```json\n?([\s\S]*?)\n?```/);
      if (jsonMatch) {
        try {
          const parsed = JSON.parse(jsonMatch[1]);
          taskData = parsed.task_breakdown || parsed.tasks || parsed;
        } catch {
          // Ignore parse errors
        }
      }

      // Also try to find raw JSON with task_breakdown
      if (!taskData) {
        const rawJsonMatch = content.match(/\{[\s\S]*"task_breakdown"[\s\S]*\}/);
        if (rawJsonMatch) {
          try {
            const parsed = JSON.parse(rawJsonMatch[0]);
            taskData = parsed.task_breakdown ||
                       parsed.reflection?.task_breakdown;
          } catch {
            // Ignore parse errors
          }
        }
      }
    }
  }

  if (!Array.isArray(taskData)) {
    return [];
  }

  return taskData.map((task: any, index: number) => ({
    id: task.id || `task-${index}`,
    description: task.description || task.task || task.content || 'Unknown task',
    status: task.status || 'pending',
    tool: task.tool || task.tool_name,
    files: task.files || task.file_paths || [],
    duration_ms: task.duration_ms,
    content: task.content,
  }));
}

// Update tasks from a coordinator response
export function updateTasksFromResponse(responseData: any) {
  const parsed = parseTaskBreakdown(responseData);
  if (parsed.length > 0) {
    tasks.set(parsed);
  }
}
