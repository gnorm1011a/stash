import json
import sys
import os
import shutil
import traceback

def main():
    raw = sys.stdin.read()
    if not raw:
        print(json.dumps({"success": False, "error": "No input received"}))
        return

    try:
        data = json.loads(raw)
        args = data.get("args", {})
        mode = args.get("mode", "")

        if mode == "open_external":
            file_path = args.get("path", "")
            if not file_path:
                print(json.dumps({"success": False, "error": "No path provided"}))
                return
            if not os.path.exists(file_path):
                print(json.dumps({"success": False, "error": "File not found: " + file_path}))
                return

            # Copy to a temp directory to avoid the Windows security warning
            # that appears for files from UNC/network locations.
            temp_dir = os.path.join(
                os.environ.get("TEMP", os.environ.get("TMP", ".")),
                "LightboxTweaks",
            )
            os.makedirs(temp_dir, exist_ok=True)

            basename = os.path.basename(file_path)
            temp_path = os.path.join(temp_dir, basename)
            shutil.copy2(file_path, temp_path)

            # Open the local temp copy with its default application (Photos app)
            os.startfile(temp_path)

            print(json.dumps({"success": True}))
        else:
            print(json.dumps({"success": False, "error": "Unknown mode: " + mode}))
    except Exception as e:
        tb = traceback.format_exc()
        print(json.dumps({"success": False, "error": str(e), "traceback": tb}))

if __name__ == "__main__":
    main()
