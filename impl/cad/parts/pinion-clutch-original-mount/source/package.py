"""Package only deliverables, sources, frozen profiles, and verification results."""
from pathlib import Path
import zipfile,hashlib,json
ROOT=Path(__file__).resolve().parents[1]
files=[]
for path in ROOT.rglob('*'):
    if not path.is_file():continue
    rel=path.relative_to(ROOT)
    if '__pycache__'in rel.parts or rel.name=='SHA256SUMS.txt':continue
    if rel.parts[:2]==('slicer','logs') and rel.name not in ['result.json','effective_settings.json']:continue
    if rel.name in ['probe.json','original.png']:continue
    # Match this folder's Git attributes before hashing generated Windows text.
    if path.suffix in {'.py','.md','.json','.txt'} or path.name in {'.gitignore','.gitattributes'}:
        path.write_bytes(path.read_bytes().replace(b'\r\n',b'\n'))
    files.append(path)
files.sort()
manifest='\n'.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(ROOT).as_posix()}'for p in files)+'\n'
(ROOT/'SHA256SUMS.txt').write_text(manifest,encoding='utf-8',newline='\n')
target=ROOT.parent/(ROOT.name+'.zip')
with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
    for p in files+[ROOT/'SHA256SUMS.txt']:
        z.write(p,Path(ROOT.name)/p.relative_to(ROOT))
with zipfile.ZipFile(target) as z:assert z.testzip() is None
print(json.dumps({'zip':str(target),'files':len(files)+1,'bytes':target.stat().st_size},indent=2))
