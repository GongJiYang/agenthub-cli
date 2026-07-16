"""Tool_Executor：对话模式下实际执行工具调用的组件。"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from .models import ToolCall, ToolResult


class ToolExecutor:
    """在对话模式下执行工具调用，不受 SkillConfig.path_rules 限制。"""

    COMMAND_TIMEOUT: int = 30  # 秒
    SEARCH_MAX_RESULTS: int = 50

    def __init__(self, workspace_root: str = "") -> None:
        self._workspace_root = workspace_root  # search_code 最大结果数

    def execute(self, tool_call: ToolCall) -> ToolResult:
        """根据工具名分发到对应方法。"""
        name = tool_call.name
        args = tool_call.args

        try:
            if name == "read_file":
                output = self.read_file(args.get("path", ""))
            elif name == "write_file":
                output = self.write_file(args.get("path", ""), args.get("content", ""))
            elif name == "run_command":
                output = self.run_command(args.get("command", ""))
            elif name == "list_directory":
                output = self.list_directory(args.get("path", "."))
            elif name == "search_code":
                output = self.search_code(
                    pattern=args.get("pattern", ""),
                    path=args.get("path", "."),
                    file_pattern=args.get("file_pattern", ""),
                )
            elif name == "run_tests":
                output = self.run_tests(
                    command=args.get("command", ""),
                    working_dir=args.get("working_dir", ""),
                )
            elif name == "add_comment":
                output = self.add_comment(
                    file_path=args.get("file", ""),
                    line=args.get("line", 0),
                    message=args.get("message", ""),
                )
            else:
                output = f"未知工具：{name}"
        except Exception as e:
            output = f"工具执行错误：{e}"

        return ToolResult(tool_call_id=tool_call.id, output=output, allowed=True)

    def read_file(self, path: str) -> str:
        """读取文件内容，文件不存在时返回错误描述字符串。"""
        try:
            return Path(path).read_text(encoding="utf-8")
        except FileNotFoundError:
            return f"错误：文件不存在：{path}"
        except PermissionError:
            return f"错误：无权限读取文件：{path}"
        except Exception as e:
            return f"错误：读取文件失败：{e}"

    def write_file(self, path: str, content: str) -> str:
        """写入文件，目标目录不存在时自动创建。"""
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return f"已写入文件：{path}"
        except PermissionError:
            return f"错误：无权限写入文件：{path}"
        except Exception as e:
            return f"错误：写入文件失败：{e}"

    def run_command(self, command: str) -> str:
        """执行 shell 命令，超时 30 秒，返回 stdout+stderr+exit_code 拼接字符串。"""
        cwd = self._workspace_root or os.getcwd()
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=self.COMMAND_TIMEOUT,
                cwd=cwd,
            )
            parts = []
            if result.stdout:
                parts.append(result.stdout)
            if result.stderr:
                parts.append(f"[stderr]\n{result.stderr}")
            parts.append(f"[exit_code: {result.returncode}]")
            return "\n".join(parts)
        except subprocess.TimeoutExpired:
            return f"错误：命令执行超时（>{self.COMMAND_TIMEOUT}秒）：{command}"
        except Exception as e:
            return f"错误：命令执行失败：{e}"

    def list_directory(self, path: str = ".") -> str:
        """列出目录内容，返回格式化字符串。"""
        try:
            p = Path(path)
            if not p.exists():
                return f"错误：目录不存在：{path}"
            if not p.is_dir():
                return f"错误：路径不是目录：{path}"

            entries = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name))
            lines = [f"{path}/"]
            for entry in entries:
                prefix = "📁 " if entry.is_dir() else "📄 "
                lines.append(f"  {prefix}{entry.name}")
            return "\n".join(lines)
        except PermissionError:
            return f"错误：无权限访问目录：{path}"
        except Exception as e:
            return f"错误：列出目录失败：{e}"

    def search_code(self, pattern: str, path: str = "", file_pattern: str = "") -> str:
        """在代码库中搜索匹配模式的文件和行。"""
        if not pattern:
            return "错误：search_code 需要提供 pattern 参数"

        search_path = Path(path) if path else (Path(self._workspace_root) if self._workspace_root else Path("."))

        try:
            if not search_path.exists():
                return f"错误：搜索路径不存在：{path or str(search_path)}"
            if not search_path.is_dir():
                return f"错误：搜索路径不是目录：{path or str(search_path)}"

            try:
                regex = re.compile(pattern)
            except re.error as e:
                return f"错误：正则表达式无效：{e}"

            file_glob = file_pattern or "*"
            matches: list[str] = []
            count = 0

            for file_path in search_path.rglob(file_glob):
                if not file_path.is_file():
                    continue
                if any(part.startswith(".") for part in file_path.relative_to(search_path).parts):
                    continue
                try:
                    content = file_path.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue

                for line_no, line in enumerate(content.splitlines(), 1):
                    if regex.search(line):
                        rel_path = file_path.relative_to(search_path)
                        matches.append(f"{rel_path}:{line_no}: {line.rstrip()}")
                        count += 1
                        if count >= self.SEARCH_MAX_RESULTS:
                            return "\n".join(matches) + f"\n... (共 {self.SEARCH_MAX_RESULTS}+ 条结果，已截断)"

            if not matches:
                return f"未找到匹配项：pattern={pattern!r}"

            return "\n".join(matches) + f"\n共 {len(matches)} 条匹配结果"

        except PermissionError:
            return f"错误：无权限搜索目录：{path}"
        except Exception as e:
            return f"错误：代码搜索失败：{e}"

    def run_tests(self, command: str = "", working_dir: str = "") -> str:
        """执行测试命令并返回结果。"""
        test_cmd = command or "pytest"
        cwd = working_dir or self._workspace_root or os.getcwd()

        # 将超时延长到 120 秒（测试通常耗时更长）
        try:
            result = subprocess.run(
                test_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=cwd,
            )
            parts = []
            if result.stdout:
                parts.append(result.stdout)
            if result.stderr:
                parts.append(f"[stderr]\n{result.stderr}")
            parts.append(f"[exit_code: {result.returncode}]")
            return "\n".join(parts)
        except subprocess.TimeoutExpired:
            return f"错误：测试执行超时（>120秒）：{test_cmd}"
        except Exception as e:
            return f"错误：测试执行失败：{e}"

    def add_comment(self, file_path: str, line: int = 0, message: str = "") -> str:
        """在代码文件中添加注释行。

        在指定行号后插入注释行。若行号为 0 则在文件末尾追加。

        Args:
            file_path: 目标文件路径。
            line: 插入注释的行号（1-based），0 表示文件末尾。
            message: 注释内容。
        """
        if not file_path:
            return "错误：add_comment 需要提供 file 参数"
        if not message:
            return "错误：add_comment 需要提供 message 参数"

        try:
            p = Path(file_path)
            if not p.exists():
                return f"错误：文件不存在：{file_path}"

            lines = p.read_text(encoding="utf-8").splitlines(keepends=True)

            # 根据文件扩展名选择注释前缀
            suffix = p.suffix.lower()
            comment_prefix = self._comment_prefix(suffix)
            comment_line = f"{comment_prefix} {message}\n"

            if line <= 0 or line > len(lines):
                # 追加到末尾
                lines.append(comment_line)
                insert_pos = len(lines) - 1
            else:
                # 在指定行号后插入（1-based → 0-based）
                lines.insert(line, comment_line)
                insert_pos = line

            p.write_text("".join(lines), encoding="utf-8")
            return f"已在 {file_path}:{insert_pos + 1} 添加注释"

        except PermissionError:
            return f"错误：无权限写入文件：{file_path}"
        except Exception as e:
            return f"错误：添加注释失败：{e}"

    @staticmethod
    def _comment_prefix(suffix: str) -> str:
        """根据文件扩展名返回注释前缀。"""
        # Python, Ruby, Shell, etc.
        if suffix in (".py", ".rb", ".sh", ".bash", ".yml", ".yaml", ".toml", ".cfg", ".ini"):
            return "#"
        # C-style: JS, TS, Java, C, C++, Go, Rust, Swift, etc.
        if suffix in (".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".cpp", ".h", ".go", ".rs", ".swift", ".kt", ".scala"):
            return "//"
        # HTML, XML, SVG
        if suffix in (".html", ".htm", ".xml", ".svg"):
            return "<!--"
        # CSS, SCSS
        if suffix in (".css", ".scss", ".less", ".sass"):
            return "/*"
        # Default
        return "#"
