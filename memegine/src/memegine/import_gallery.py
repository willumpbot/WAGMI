"""Bulk import images/videos from a local folder into the gallery."""
from pathlib import Path
from .gallery import save as gallery_save
from .config import settings


def import_folder(folder_path: str, tags: list[str] = None) -> int:
    """Import all images/videos from a folder into the gallery.

    Args:
        folder_path: Path to folder with images/videos
        tags: Tags to apply to all imported items (e.g., ["spongebob", "meme"])

    Returns:
        Count of files imported
    """
    if tags is None:
        tags = []

    folder = Path(folder_path)
    if not folder.exists() or not folder.is_dir():
        print(f"❌ Folder not found: {folder_path}")
        return 0

    # Supported extensions
    supported = {'.jpg', '.jpeg', '.png', '.gif', '.mp4', '.webm', '.mov', '.avi'}

    files = [f for f in folder.rglob('*') if f.suffix.lower() in supported]

    if not files:
        print(f"❌ No images/videos found in {folder_path}")
        return 0

    count = 0
    for file_path in files:
        try:
            with open(file_path, 'rb') as f:
                file_bytes = f.read()

            item = gallery_save(
                file_bytes,
                file_path.name,
                tags=tags + ['bulk-import'],
                energy=3,
                uploader_id=None,
            )
            count += 1
            print(f"[OK] Imported: {file_path.name}")
        except Exception as e:
            print(f"[FAIL] {file_path.name}: {e}")

    print(f"\n[DONE] Imported {count} files to gallery!")
    return count


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m memegine.import_gallery <folder_path> [tag1] [tag2] ...")
        print("\nExample:")
        print("  python -m memegine.import_gallery ~/Videos/spongebob spongebob meme")
        sys.exit(1)

    folder = sys.argv[1]
    tags = sys.argv[2:] if len(sys.argv) > 2 else []

    import_folder(folder, tags)
