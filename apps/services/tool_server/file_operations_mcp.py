"""
orchestrator/file_operations_mcp.py

Token-aware file reading with smart chunking for large files.
Ensures file previews stay within 2k token budget to prevent context overflow.
"""
from __future__ import annotations

import os
import logging
from typing import Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class TokenAwareFileReader:
    """Read files with token budget awareness"""

    MAX_PREVIEW_TOKENS = 2000  # Fits within 3k context budget (leaves room for other context)
    CHARS_PER_TOKEN = 4  # Rough estimate: 1 token ≈ 4 characters
    MAX_PREVIEW_CHARS = MAX_PREVIEW_TOKENS * CHARS_PER_TOKEN  # ~8KB

    @classmethod
    async def read_file_smart(
        cls,
        file_path: str,
        offset: int = 0,
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Read file with token-aware truncation.

        Args:
            file_path: Absolute path to file
            offset: Character offset to start reading from
            limit: Max characters to read (optional)

        Returns:
            {
                "content": str,
                "truncated": bool,
                "total_size": int,
                "loaded_size": int,
                "tokens_estimate": int,
                "message": str (if truncated)
            }
        """
        try:
            if not os.path.exists(file_path):
                return {
                    "error": f"File not found: {file_path}",
                    "content": "",
                    "truncated": False
                }

            file_size = os.path.getsize(file_path)

            # Small file: load normally
            if file_size <= cls.MAX_PREVIEW_CHARS:
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                    return {
                        "content": content,
                        "truncated": False,
                        "total_size": file_size,
                        "loaded_size": len(content),
                        "tokens_estimate": len(content) // cls.CHARS_PER_TOKEN
                    }
                except Exception as e:
                    logger.error(f"Error reading file {file_path}: {e}")
                    return {
                        "error": str(e),
                        "content": "",
                        "truncated": False
                    }

            # Large file: preview with line boundaries
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    f.seek(offset)
                    preview_lines = []
                    chars_read = 0

                    # Read until we hit budget or EOF
                    for line in f:
                        if chars_read + len(line) > cls.MAX_PREVIEW_CHARS:
                            break
                        preview_lines.append(line)
                        chars_read += len(line)

                content = ''.join(preview_lines)
                tokens_estimate = chars_read // cls.CHARS_PER_TOKEN

                return {
                    "content": content,
                    "truncated": True,
                    "total_size": file_size,
                    "loaded_size": chars_read,
                    "tokens_estimate": tokens_estimate,
                    "next_offset": offset + chars_read,
                    "message": f"Large file ({file_size / 1024 / 1024:.1f}MB). Showing ~{tokens_estimate} tokens. Use offset={offset + chars_read} for more."
                }
            except Exception as e:
                logger.error(f"Error reading large file {file_path}: {e}")
                return {
                    "error": str(e),
                    "content": "",
                    "truncated": False
                }

        except Exception as e:
            logger.error(f"Unexpected error in read_file_smart: {e}")
            return {
                "error": str(e),
                "content": "",
                "truncated": False
            }


# MCP-style tool functions
async def read_file_chunked(
    file_path: str,
    offset: int = 0,
    limit: Optional[int] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    MCP tool endpoint: Read file with smart chunking.

    Tool signature:
    {
        "name": "file.read_chunked",
        "description": "Read large files with token-aware chunking",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "offset": {"type": "integer", "default": 0},
                "limit": {"type": "integer", "optional": true}
            },
            "required": ["file_path"]
        }
    }
    """
    return await TokenAwareFileReader.read_file_smart(file_path, offset, limit)

async def file_read_outline(
    file_path: str,
    symbol_filter: Optional[str] = None,
    include_docstrings: bool = True,
    **kwargs
) -> Dict[str, Any]:
    """
    Read file outline with symbol table (functions, classes).
    
    MCP tool signature:
    {
        "name": "file.read_outline",
        "description": "Get file structure with symbols, TOC, and suggested chunks",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "symbol_filter": {"type": "string", "optional": true, "description": "Regex pattern like 'class|def'"},
                "include_docstrings": {"type": "boolean", "default": true}
            },
            "required": ["file_path"]
        }
    }
    
    Returns:
        {
            "symbols": [{"type": "class", "name": "AuthManager", "line": 42, "docstring": "..."}],
            "toc": "Table of contents markdown",
            "file_info": {"lines": 150, "size_kb": 8},
            "chunks": [{"offset": 0, "limit": 50, "description": "AuthManager class"}]
        }
    """
    import re
    
    if not os.path.exists(file_path):
        return {"error": f"File not found: {file_path}"}
    
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            lines = content.split('\n')
    except Exception as e:
        return {"error": f"Failed to read file: {str(e)}"}
    
    # Extract symbols (Python for now)
    symbols = []
    if file_path.endswith('.py'):
        symbols = _extract_python_symbols(lines, include_docstrings)
    elif file_path.endswith(('.js', '.ts', '.jsx', '.tsx')):
        symbols = _extract_js_symbols(lines)
    
    # Filter symbols if pattern provided
    if symbol_filter:
        try:
            pattern = re.compile(symbol_filter, re.IGNORECASE)
            symbols = [s for s in symbols if pattern.search(s["type"]) or pattern.search(s["name"])]
        except re.error:
            return {"error": f"Invalid regex pattern: {symbol_filter}"}
    
    # Generate TOC
    toc = _generate_toc(symbols)
    
    # File info
    file_info = {
        "lines": len(lines),
        "size_kb": len(content) // 1024,
        "language": "python" if file_path.endswith('.py') else "javascript"
    }
    
    # Generate chunk suggestions
    chunks = _suggest_chunks(symbols, len(lines))
    
    return {
        "symbols": symbols[:50],  # Cap at 50 symbols
        "toc": toc,
        "file_info": file_info,
        "chunks": chunks[:10]  # Cap at 10 chunks
    }


def _extract_python_symbols(lines: list, include_docstrings: bool) -> list:
    """Extract classes and functions from Python code."""
    import re
    
    symbols = []
    
    for i, line in enumerate(lines, 1):
        # Class definition
        class_match = re.match(r'^(\s*)class\s+(\w+)', line)
        if class_match:
            indent = len(class_match.group(1))
            name = class_match.group(2)
            
            docstring = None
            if include_docstrings and i < len(lines):
                docstring = _extract_docstring(lines, i)
            
            symbols.append({
                "type": "class",
                "name": name,
                "line": i,
                "indent": indent,
                "docstring": docstring
            })
        
        # Function definition
        func_match = re.match(r'^(\s*)(?:async\s+)?def\s+(\w+)', line)
        if func_match:
            indent = len(func_match.group(1))
            name = func_match.group(2)
            
            docstring = None
            if include_docstrings and i < len(lines):
                docstring = _extract_docstring(lines, i)
            
            symbols.append({
                "type": "function",
                "name": name,
                "line": i,
                "indent": indent,
                "docstring": docstring
            })
    
    return symbols


def _extract_js_symbols(lines: list) -> list:
    """Extract functions and classes from JavaScript/TypeScript."""
    import re
    
    symbols = []
    
    for i, line in enumerate(lines, 1):
        # Class definition
        class_match = re.match(r'^\s*(?:export\s+)?(?:default\s+)?class\s+(\w+)', line)
        if class_match:
            symbols.append({
                "type": "class",
                "name": class_match.group(1),
                "line": i,
                "indent": len(line) - len(line.lstrip())
            })
        
        # Function definition (various forms)
        func_patterns = [
            r'^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)',  # function foo()
            r'^\s*(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:\([^)]*\)|[^=]+)\s*=>',  # const foo = () =>
            r'^\s*(?:async\s+)?(\w+)\s*\([^)]*\)\s*{',  # foo() {
        ]
        
        for pattern in func_patterns:
            func_match = re.match(pattern, line)
            if func_match:
                symbols.append({
                    "type": "function",
                    "name": func_match.group(1),
                    "line": i,
                    "indent": len(line) - len(line.lstrip())
                })
                break
    
    return symbols


def _extract_docstring(lines: list, start_line: int) -> Optional[str]:
    """Extract docstring after a class/function definition."""
    if start_line >= len(lines):
        return None
    
    next_line = lines[start_line].strip()
    
    # Check for """ or '''
    if next_line.startswith('"""') or next_line.startswith("'''"):
        quote = '"""' if next_line.startswith('"""') else "'''"
        
        # Single line docstring
        if next_line.count(quote) == 2:
            return next_line.strip(quote).strip()
        
        # Multi-line docstring
        docstring_lines = [next_line.strip(quote)]
        for line in lines[start_line + 1:min(start_line + 10, len(lines))]:
            if quote in line:
                docstring_lines.append(line.split(quote)[0].strip())
                break
            docstring_lines.append(line.strip())
        
        # Return first 60 chars
        full_doc = " ".join(docstring_lines)
        return full_doc[:60] + "..." if len(full_doc) > 60 else full_doc
    
    return None


def _generate_toc(symbols: list) -> str:
    """Generate table of contents markdown."""
    if not symbols:
        return "# No symbols found"
    
    toc_lines = ["# Table of Contents\n"]
    
    for sym in symbols:
        indent = "  " * (sym.get("indent", 0) // 4)
        icon = "📦" if sym["type"] == "class" else "⚙️"
        line_info = f"L{sym['line']}"
        
        toc_lines.append(f"{indent}{icon} **{sym['name']}** ({line_info})")
        
        if sym.get("docstring"):
            doc_preview = sym["docstring"]
            toc_lines.append(f"{indent}  _{doc_preview}_")
    
    return "\n".join(toc_lines[:50])  # Cap at 50 lines


def _suggest_chunks(symbols: list, total_lines: int) -> list:
    """Suggest file chunks to read based on symbols."""
    if not symbols:
        return []
    
    chunks = []
    
    for i, sym in enumerate(symbols):
        start_line = max(1, sym["line"] - 1)  # Start 1 line before
        
        # Estimate end line (next symbol or +50 lines)
        if i + 1 < len(symbols):
            end_line = symbols[i + 1]["line"] - 1
        else:
            end_line = min(start_line + 50, total_lines)
        
        chunks.append({
            "offset": start_line,
            "limit": end_line - start_line,
            "description": f"{sym['type']} {sym['name']}",
            "line_range": f"{start_line}-{end_line}"
        })
    
    return chunks
