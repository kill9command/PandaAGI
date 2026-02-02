import { writable, get } from 'svelte/store';

// Types
export interface TerminalLine {
  text: string;
  type: 'stdout' | 'stderr' | 'info';
  timestamp: number;
}

// Stores
export const terminalLines = writable<TerminalLine[]>([]);
export const terminalVisible = writable<boolean>(false);

// Actions
export function addTerminalOutput(text: string, type: 'stdout' | 'stderr' | 'info' = 'stdout') {
  terminalLines.update((lines) => [
    ...lines,
    {
      text,
      type,
      timestamp: Date.now(),
    },
  ]);

  // Auto-show terminal when output is added
  terminalVisible.set(true);
}

export function clearTerminal() {
  terminalLines.set([]);
}

export function toggleTerminal() {
  terminalVisible.update((v) => !v);
}

export function showTerminal() {
  terminalVisible.set(true);
}

export function hideTerminal() {
  terminalVisible.set(false);
}

// Parse bash output from response data
// Handles multiple formats:
// 1. tool_outputs array with tool === 'bash.execute' and result.stdout/stderr
// 2. tool_results/tools array with tool/tool_name === 'bash' and direct stdout/stderr
// 3. SSE tool_result events with tool and raw_result
export function parseBashOutput(responseData: any) {
  // Support multiple field names for tool results
  const toolResults = responseData?.tool_outputs || responseData?.tool_results || responseData?.tools || [];

  for (const result of toolResults) {
    // Check if this is a bash tool (various naming conventions)
    const toolName = result.tool || result.tool_name || '';
    const isBash = toolName === 'bash' || toolName === 'bash.execute' || toolName.startsWith('bash.');

    if (isBash) {
      // Show the command being executed (if available)
      const command = result.args?.command || result.command || result.raw_result?.command;
      if (command) {
        addTerminalOutput(`$ ${command}`, 'info');
      }

      // Handle nested result structure (tool_outputs format from vanilla JS)
      const output = result.result || result.raw_result || result;

      if (output.stdout) {
        addTerminalOutput(output.stdout, 'stdout');
      }
      if (output.stderr) {
        addTerminalOutput(output.stderr, 'stderr');
      }
      if (output.error || result.error) {
        addTerminalOutput(`Error: ${output.error || result.error}`, 'stderr');
      }

      // Show exit code if non-zero
      const exitCode = output.exit_code;
      if (exitCode !== undefined && exitCode !== 0) {
        addTerminalOutput(`Exit code: ${exitCode}`, 'stderr');
      }
    }
  }
}
