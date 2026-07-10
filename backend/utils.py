def format_elapsed(seconds: float) -> str:
    mins, secs = divmod(int(seconds), 60)
    return f"{mins}分{secs}秒" if mins else f"{secs}秒"
