"""Run the official portable slicer using workspace-only user data."""
from pathlib import Path
import os, subprocess, sys

BASE=Path(__file__).resolve().parent
EXE=BASE/'bambu_studio_2.8.2.61/bambu-studio.exe'
DATA=BASE/'bambu_cli_userdata'

def run(args, output_path=None, timeout=1800):
    env=os.environ.copy()
    for key,name in [('APPDATA','roaming'),('LOCALAPPDATA','local')]:
        d=DATA/name;d.mkdir(parents=True,exist_ok=True);env[key]=str(d)
    startup=subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow=0
    cmd=[str(EXE),'--datadir',str(DATA/'settings'),*map(str,args)]
    proc=subprocess.run(cmd,cwd=str(EXE.parent),env=env,stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,startupinfo=startup,creationflags=subprocess.CREATE_NO_WINDOW,timeout=timeout)
    text=proc.stdout.decode('utf-8',errors='replace')
    if output_path:
        p=Path(output_path);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding='utf-8')
    return proc.returncode,text

if __name__=='__main__':
    code,text=run(sys.argv[1:])
    sys.stdout.buffer.write(text.encode('utf-8'))
    raise SystemExit(code)
