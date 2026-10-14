"""Double-click bootstrap: locate conda, prepare the dedicated env, launch Qt."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
CHECK = "import sys; assert sys.version_info >= (3,12); import PyQt6.QtWidgets, PyQt6.QtWebEngineWidgets, requests, icalendar, recurring_ical_events, tzdata"


def base_candidates():
    user = Path.home()
    local = Path(os.environ.get("LOCALAPPDATA", user / "AppData" / "Local"))
    roots = [Path(sys.executable).parent]
    for command in (os.environ.get("CONDA_EXE"), shutil.which("conda")):
        if command:
            path = Path(command)
            roots.extend([path.parent, path.parent.parent])
    for prefix in (Path(os.environ.get("ProgramData", "C:/ProgramData")), user, local, local / "Programs", Path(os.environ.get("ProgramFiles", "C:/Program Files"))):
        roots.extend([prefix / "anaconda3", prefix / "miniconda3"])
    return list(dict.fromkeys(roots))


def conda_command(roots):
    for root in roots:
        python = root / "python.exe"
        if python.is_file() and (root / "Lib" / "site-packages" / "conda").is_dir():
            return [str(python), "-m", "conda"]
    return None


def locate_environment(roots, command):
    candidates = [Path.home() / ".conda" / "envs" / "campo-reader"]
    candidates.extend(root / "envs" / "campo-reader" for root in roots)
    for candidate in candidates:
        if (candidate / "python.exe").is_file():
            return candidate
    if command:
        result = subprocess.run(command + ["env", "list", "--json"], capture_output=True, text=True, check=True)
        for path in json.loads(result.stdout).get("envs", []):
            candidate = Path(path)
            if candidate.name.lower() == "campo-reader" and (candidate / "python.exe").is_file():
                return candidate
    return None


def dependencies_ready(python):
    return subprocess.run([str(python), "-c", CHECK], capture_output=True).returncode == 0


def prepare_environment():
    roots = base_candidates()
    command = conda_command(roots)
    environment = locate_environment(roots, command)
    if environment is None:
        if not command:
            raise RuntimeError("Conda was not found. Install Anaconda/Miniconda, then try again.")
        print("[Campo Reader] First launch: creating the conda environment. This may take a few minutes.", flush=True)
        subprocess.run(command + ["env", "create", "--file", str(ROOT / "environment.yml"), "--yes"], check=True)
        environment = locate_environment(roots, command)
        if environment is None:
            raise RuntimeError("The new campo-reader environment could not be located.")
    python = environment / "python.exe"
    if not dependencies_ready(python):
        if not command:
            raise RuntimeError("Dependencies are missing and conda is unavailable. See README.md.")
        print("[Campo Reader] Preparing Python and repairing dependencies...", flush=True)
        subprocess.run(command + ["install", "--prefix", str(environment), "python=3.12", "pip", "--yes"], check=True)
        subprocess.run([str(python), "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")], check=True)
        if not dependencies_ready(python):
            raise RuntimeError("Dependency check failed after installation. See README.md.")
    return environment


def main():
    parser = argparse.ArgumentParser(description="Prepare and launch Campo Reader")
    parser.add_argument("--check", action="store_true", help="Prepare and verify without opening a window")
    args, app_args = parser.parse_known_args()
    try:
        print("[Campo Reader] Checking environment...", flush=True)
        environment = prepare_environment()
        if args.check:
            print("[Campo Reader] Ready. " + str(environment))
            return 0
        executable = environment / "pythonw.exe"
        if not executable.is_file():
            executable = environment / "python.exe"
        (ROOT / "data").mkdir(exist_ok=True)
        with (ROOT / "data" / "launch-errors.log").open("ab") as log:
            process = subprocess.Popen([str(executable), str(ROOT / "main.py")] + app_args, cwd=ROOT,
                                       stdout=log, stderr=log, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                code = process.wait(timeout=1)
                if code:
                    raise RuntimeError("The app exited during startup. Check data/launch-errors.log.")
            except subprocess.TimeoutExpired:
                pass
        print("[Campo Reader] Started.")
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print("[Campo Reader] Could not start: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
