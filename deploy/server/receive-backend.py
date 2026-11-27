#!/usr/bin/env python3
"""Server side of the GitHub deploy: build a commit of the public main branch and switch the backend to it.

Install root-owned outside the project folder; it runs as the owner of the rootless Docker daemon (see README).
Usage: receive-backend.py <project folder with compose.json> <git url>; stdin: one line with the commit id.
Only commits that are on main can be deployed, the caller cannot hand in code of its own.
"""
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


def run(*command, **options):
    print("+", " ".join(command), flush=True)
    return subprocess.run(command, check=True, **options)


def output(*command):
    return subprocess.run(command, check=True, stdout=subprocess.PIPE, text=True).stdout.strip()


def deploy(project, repository, commit):
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("A full commit id is required")
    compose = project / "compose.json"
    previous = project / "compose.previous.json"
    if not compose.is_file():
        raise ValueError(f"{compose} is missing")
    with (project / ".deploy.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        source = project / "source.git"
        if not source.is_dir():
            run("git", "init", "--quiet", "--bare", str(source))
        git = ("git", "--git-dir", str(source))
        run(*git, "fetch", "--quiet", repository, "+refs/heads/main:refs/heads/main")
        if subprocess.run([*git, "merge-base", "--is-ancestor", commit, "refs/heads/main"]).returncode:
            raise ValueError("Commit is not on main")

        tag = f"miniworlds-backend:{commit}"
        with subprocess.Popen([*git, "archive", "--format=tar", commit], stdout=subprocess.PIPE) as archive:
            run("docker", "build", "--pull", "--build-arg", f"BACKEND_REVISION={commit}", "-t", tag, "-", stdin=archive.stdout)
        if archive.returncode:
            raise RuntimeError("git archive failed")
        image = output("docker", "image", "inspect", "--format", "{{.Id}}", tag)

        up = ("docker", "compose", "-f", str(compose), "up", "-d", "--wait", "--wait-timeout", "120", "backend")
        # backup with recovery verification, made by the release that is running now
        run("docker", "compose", "-f", str(compose), "run", "--rm", "backup")
        config = json.loads(compose.read_text())
        for service in ("backend", "backup"):
            config["services"][service]["image"] = image
        shutil.copy2(compose, previous)
        try:
            temporary = project / "compose.next.json"
            temporary.write_text(json.dumps(config, indent=2) + "\n")
            temporary.replace(compose)
            run(*up)
        except BaseException:
            print("New release failed, going back to the previous one", file=sys.stderr, flush=True)
            shutil.copy2(previous, compose)
            run(*up)
            raise
    return {"commit": commit, "image": image}


if __name__ == "__main__":
    try:
        runtime = f"/run/user/{os.getuid()}"
        os.environ.setdefault("XDG_RUNTIME_DIR", runtime)
        os.environ.setdefault("DOCKER_HOST", f"unix://{runtime}/docker.sock")
        project = Path(sys.argv[1])
        os.chdir(project)
        print(json.dumps(deploy(project, sys.argv[2], sys.stdin.readline(100).strip())))
    except Exception as error:
        print(f"Deploy failed: {error}", file=sys.stderr)
        raise SystemExit(1)
