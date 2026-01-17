import os
from pathlib import Path
import subprocess
import shutil
import re
import yaml


def rebuild_interceptor_with(
    img, interceptor_dir=Path(__file__).parent.parent / "rocket_interceptor"
) -> bool:

    original_cwd = os.getcwd()
    os.chdir(interceptor_dir)
    try:
        # Write to config.yaml instead of replacing code
        config_file = interceptor_dir / "config.yaml"
        config_content = f'image: "{img}"\n'
        config_file.write_text(config_content, encoding="utf-8")
        print(f"✓ Config updated: {config_file}")
        subprocess.run(["./build.sh"], check=True)
        os.chdir(original_cwd)
        return True
    except Exception as e:
        print(f"Error occurred while rebuilding interceptor: {e}")
        os.chdir(original_cwd)
        return False


if __name__ == "__main__":
    with open("evotest.yaml", "r") as f:
        config = yaml.safe_load(f)
    rebuild_interceptor_with(img=["ripple-image"])
