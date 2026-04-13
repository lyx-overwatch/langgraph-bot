
from pathlib import Path

WORKDIR = Path.cwd() / "workspace"
MAX_FILE_SIZE_BYTES = 200_000
BLOCKED_PATH_PARTS = {
	".git",
	".venv",
	"node_modules",
	"__pycache__",
	"debugger",
}
ALLOWED_WRITE_SUFFIXES = {
	".md",
	".pdf",
	".html",
	".txt",
	".json",
	".yaml",
	".yml",
	".py",
	".toml",
}

def safe_path(p: str) -> Path:
	path = (WORKDIR / p).resolve()
	if not path.is_relative_to(WORKDIR):
		raise ValueError(f"Path escapes workspace: {p}")
	# if any(part in BLOCKED_PATH_PARTS for part in path.relative_to(WORKDIR).parts):
	# 	raise ValueError(f"Path is blocked: {p}")
	return path

def run_read(path: str, limit: int | None = None) -> str:
	try:
		fp = safe_path(path)
		if fp.stat().st_size > MAX_FILE_SIZE_BYTES:
			return f"Error: File too large to read safely: {path}"
		lines = fp.read_text().splitlines()
		if limit and limit < len(lines):
			lines = lines[:limit] + [f"... ({len(lines) - limit} more)"]
		return "\n".join(lines)[:50000]
	except Exception as e:
		return f"Error: {e}"


def run_write(path: str, content: str) -> str:
	try:
		fp = safe_path(path)
		# if fp.suffix and fp.suffix not in ALLOWED_WRITE_SUFFIXES:
		# 	return f"Error: Writing files of type '{fp.suffix}' is not allowed"
		if len(content.encode()) > MAX_FILE_SIZE_BYTES:
			return f"Error: Content too large to write safely: {path}"
		fp.parent.mkdir(parents=True, exist_ok=True)
		fp.write_text(content)
		return f"Wrote {len(content)} bytes to {path}"
	except Exception as e:
		return f"Error: {e}"


def run_edit(path: str, old_text: str, new_text: str) -> str:
	try:
		fp = safe_path(path)
		# if fp.suffix and fp.suffix not in ALLOWED_WRITE_SUFFIXES:
		# 	return f"Error: Editing files of type '{fp.suffix}' is not allowed"
		c = fp.read_text()
		if len(c.encode()) > MAX_FILE_SIZE_BYTES:
			return f"Error: File too large to edit safely: {path}"
		if old_text not in c:
			return f"Error: Text not found in {path}"
		fp.write_text(c.replace(old_text, new_text, 1))
		return f"Edited {path}"
	except Exception as e:
		return f"Error: {e}"