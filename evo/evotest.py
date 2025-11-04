import yaml
import os
from pathlib import Path
import subprocess
import shutil
from rebuild_interceptor import rebuild_interceptor_with

# dirs
CUR_DIR = Path(__file__).parent
ROCKET_DIR = CUR_DIR.parent
INTERCEPTOR_DIR = ROCKET_DIR / "rocket_interceptor"

def setup_interceptor(config):
    (CUR_DIR/"bin").mkdir(parents=True, exist_ok=True)
    ripple_image = config["ripple-image"]
    print(f"config.ripple-image = {ripple_image}, type = {type(ripple_image)}")
    # docker pull 这个image，确保本地有缓存
    print(f"Pulling docker image {ripple_image}...")
    subprocess.run(["docker", "pull", ripple_image], check=True)
    
    image_bin = CUR_DIR / "bin" / ripple_image.replace("/", "-")

    if not image_bin.exists():
        print(f"{image_bin} not built, building...")
        success = rebuild_interceptor_with(
            img=ripple_image,
            interceptor_dir=INTERCEPTOR_DIR,
            dest=image_bin
        )
        if not success:
            print("Rebuild interceptor failed")
            return
    
    assert image_bin.exists(), f"{image_bin} not exists after rebuild"
    
    # 将image_bin拷贝到INTERCEPTOR_DIR下以供使用
    target_path = INTERCEPTOR_DIR / "rocket-interceptor"
    shutil.copy2(image_bin, target_path)
    print(f"Copied {image_bin} to {target_path}")



def main(config):
    setup_interceptor(config)

    



if __name__ == "__main__":
    with open("evotest.yaml", "r") as f:
        config = yaml.safe_load(f)
        main(config)
