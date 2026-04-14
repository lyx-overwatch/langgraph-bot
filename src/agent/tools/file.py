
from pathlib import Path

WORKDIR = Path.cwd() / "workspace"
MAX_FILE_SIZE_BYTES = 200_000
MAX_RETURN_CHARS = 50_000
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
READ_ENCODINGS = (
	"utf-8",
	"utf-8-sig",
	"gb18030",
	"gbk",
	"latin-1",
)


def _decode_text(data: bytes) -> tuple[str, str]:
	for encoding in READ_ENCODINGS:
		try:
			return data.decode(encoding), encoding
		except UnicodeDecodeError:
			continue
	return data.decode("utf-8", errors="replace"), "utf-8"

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
		if not fp.is_file():
			return f"Error: File not found: {path}"
		if fp.stat().st_size > MAX_FILE_SIZE_BYTES:
			return f"Error: File too large to read safely: {path}"
		text, _ = _decode_text(fp.read_bytes())
		lines = text.splitlines()
		if limit and limit < len(lines):
			lines = lines[:limit] + [f"... ({len(lines) - limit} more)"]
		return "\n".join(lines)[:MAX_RETURN_CHARS]
	except Exception as e:
		return f"Error: {e}"


def run_write(path: str, content: str) -> str:
	try:
		fp = safe_path(path)
		# if fp.suffix and fp.suffix not in ALLOWED_WRITE_SUFFIXES:
		# 	return f"Error: Writing files of type '{fp.suffix}' is not allowed"
		content_bytes = content.encode("utf-8")
		if len(content_bytes) > MAX_FILE_SIZE_BYTES:
			return f"Error: Content too large to write safely: {path}"
		fp.parent.mkdir(parents=True, exist_ok=True)
		fp.write_text(content, encoding="utf-8")
		return f"Wrote {len(content_bytes)} bytes to {path}"
	except Exception as e:
		return f"Error: {e}"


def run_edit(path: str, old_text: str, new_text: str) -> str:
	try:
		fp = safe_path(path)
		# if fp.suffix and fp.suffix not in ALLOWED_WRITE_SUFFIXES:
		# 	return f"Error: Editing files of type '{fp.suffix}' is not allowed"
		if not fp.is_file():
			return f"Error: File not found: {path}"
		raw = fp.read_bytes()
		if len(raw) > MAX_FILE_SIZE_BYTES:
			return f"Error: File too large to edit safely: {path}"
		c, encoding = _decode_text(raw)
		if old_text not in c:
			return f"Error: Text not found in {path}"
		updated = c.replace(old_text, new_text, 1)
		fp.write_text(updated, encoding=encoding)
		return f"Edited {path}"
	except Exception as e:
		return f"Error: {e}"