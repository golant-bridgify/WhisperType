"""
Download all WhisperType models for offline use.
Run this once to pre-download all models so they're available instantly.
"""
import sys
import os

MODELS = {
    "ivrit-ai/whisper-large-v3-turbo-ct2": ("Hebrew Turbo ⭐", "~1.5 GB"),
    "ivrit-ai/whisper-large-v3-ct2": ("Hebrew Large", "~3 GB"),
    "distil-large-v3": ("English Distil (fast + accurate)", "~1.5 GB"),
    "small": ("General Small", "~460 MB"),
    "medium": ("General Medium", "~1.5 GB"),
    "large-v3": ("General Large-v3", "~3 GB"),
    "large-v3-turbo": ("General Large-v3 Turbo", "~1.6 GB"),
}


def download_model(model_id, label, size):
    """Download a single model."""
    print(f"\n{'='*60}")
    print(f"  Downloading: {label} ({model_id})")
    print(f"  Size: {size}")
    print(f"{'='*60}")

    try:
        from faster_whisper import WhisperModel
        model = WhisperModel(
            model_id,
            device="cpu",
            compute_type="int8",
            cpu_threads=1,  # Minimal threads, just downloading
        )
        del model  # Free memory
        print(f"  ✓ {label} downloaded successfully!")
        return True
    except Exception as e:
        print(f"  ✗ Failed to download {label}: {e}")
        return False


def main():
    print("=" * 60)
    print("  WhisperType - Model Downloader")
    print("  This will download all speech recognition models")
    print("=" * 60)

    # Check if user wants specific models or all
    if len(sys.argv) > 1 and sys.argv[1] == "--hebrew-only":
        selected = {k: v for k, v in MODELS.items() if k.startswith("ivrit-ai")}
        print("\n  Downloading Hebrew models only...")
    elif len(sys.argv) > 1 and sys.argv[1] == "--recommended":
        selected = {"ivrit-ai/whisper-large-v3-turbo-ct2": MODELS["ivrit-ai/whisper-large-v3-turbo-ct2"]}
        print("\n  Downloading recommended model only...")
    else:
        selected = MODELS
        total_size = "~11 GB"
        print(f"\n  Total download size: {total_size}")
        print(f"  Models to download: {len(selected)}")

    print()
    success = 0
    failed = 0

    for model_id, (label, size) in selected.items():
        if download_model(model_id, label, size):
            success += 1
        else:
            failed += 1

    print(f"\n{'='*60}")
    print(f"  Done! {success} models downloaded, {failed} failed.")
    if failed == 0:
        print("  All models are ready for offline use!")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
