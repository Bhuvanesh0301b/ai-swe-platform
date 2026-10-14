from pathlib import Path
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

CODE_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx"}


def _read_source_files(repo_path: Path, file_list: list) -> dict:
    """Reads every source code file into memory as {relative_path: content}."""
    files = {}
    for rel_path in file_list:
        if Path(rel_path).suffix not in CODE_EXTENSIONS:
            continue
        full_path = repo_path / rel_path
        try:
            files[rel_path] = full_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
    return files


def rank_files_by_relevance(task_description: str, repo_local_path: str, file_list: list) -> list:
    """
    Ranks source files by relevance to the task description using TF-IDF +
    cosine similarity - a lightweight, deterministic retrieval technique that
    needs no model downloads and runs instantly, even on modest hardware.

    Returns a list of dicts sorted by descending relevance:
    [{"path": "music_player.py", "score": 0.42, "content": "..."}, ...]

    Falls back to a neutral zero-score ordering if there are too few files or
    the vectorizer can't build a vocabulary (e.g. all files are empty).
    """
    repo_path = Path(repo_local_path)
    files = _read_source_files(repo_path, file_list)

    if not files:
        return []

    paths = list(files.keys())
    contents = list(files.values())

    if len(paths) == 1:
        return [{"path": paths[0], "score": 1.0, "content": contents[0]}]

    try:
        vectorizer = TfidfVectorizer(stop_words="english", max_features=5000)
        # Fit on file contents + the task description together, so they share
        # the same vocabulary/vector space and can be meaningfully compared.
        tfidf_matrix = vectorizer.fit_transform(contents + [task_description])

        file_vectors = tfidf_matrix[:-1]
        task_vector = tfidf_matrix[-1]

        similarities = cosine_similarity(task_vector, file_vectors)[0]
    except ValueError:
        # Empty vocabulary (e.g. all whitespace/comments-only files) - fall
        # back to treating all files as equally relevant.
        similarities = [0.0] * len(paths)

    ranked = sorted(
        zip(paths, contents, similarities),
        key=lambda x: x[2],
        reverse=True,
    )

    return [{"path": p, "score": round(float(s), 4), "content": c} for p, c, s in ranked]