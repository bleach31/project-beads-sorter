"""Offline reference slicing for the repository's P1S / 0.4 mm / PLA setup."""
from pathlib import Path
import sys, json, shutil, zipfile
ROOT = Path(__file__).resolve().parents[1]
TOOLS = Path('C:/Users/10001176180/Documents/BSP/.tools')
import run_bambu
run_bambu.EXE = TOOLS/'bambu_studio_2.8.2.61'/'bambu-studio.exe'
run_bambu.DATA = TOOLS/'pinion_clutch_6mm_slicer_userdata'
settings = ROOT/'slicer'/'settings'
logs = ROOT/'slicer'/'logs'
settings.mkdir(parents=True, exist_ok=True)
logs.mkdir(parents=True, exist_ok=True)
(ROOT/'print').mkdir(exist_ok=True)
reference = ROOT.parent/'feeder_final_set'/'slicer'/'feeder'/'settings'
if not reference.is_dir():
    reference = settings
for filename in ['machine.json','filament_pla.json','provenance.json','official_release.json']:
    if (reference/filename).resolve() != (settings/filename).resolve():
        shutil.copy2(reference/filename, settings/filename)
p = json.loads((reference/'process.json').read_text(encoding='utf-8'))
p.update(name='PLA clutch 6mm trials 0.12 mm P1S',layer_height='0.12',
    initial_layer_print_height='0.2',wall_loops='4',wall_generator='arachne',
    sparse_infill_density='100%',sparse_infill_pattern='concentric',
    top_shell_layers='6',bottom_shell_layers='6',brim_type='no_brim',brim_width='0',
    enable_prime_tower='0',enable_support='0',raft_layers='0',
    outer_wall_line_width='0.4',inner_wall_line_width='0.4',line_width='0.4',initial_layer_line_width='0.42',
    outer_wall_speed=['25','25'],inner_wall_speed=['35','35'],
    small_perimeter_speed=['50%','50%'],small_perimeter_threshold=['10','10'],
    initial_layer_speed=['20','20'],initial_layer_infill_speed=['25','25'],
    bridge_speed=['20','20'],sparse_infill_speed=['40','40'],internal_solid_infill_speed=['35','35'],
    top_surface_speed=['25','25'],elefant_foot_compensation='0.15',
    xy_hole_compensation='0',xy_contour_compensation='0',resolution='0.005',
    seam_position='aligned',print_sequence='by layer',only_one_wall_top='0')
(settings/'process.json').write_text(json.dumps(p,indent=2),encoding='utf-8')
common=['--debug','3','--load-settings',str(settings/'machine.json')+';'+str(settings/'process.json'),
    '--load-filaments',str(settings/'filament_pla.json'),'--curr-bed-type','Textured PEI Plate',
    '--arrange','0','--orient','0','--outputdir',str(logs)]
source=ROOT/'plates'/'00_all_trials_geometry.3mf'
print('Exporting configured P1S project',flush=True)
code,text=run_bambu.run([*common,'--export-3mf','01_all_trials_P1S_PLA.3mf',str(source)],logs/'export.log')
assert code==0,text[-2500:]
shutil.copy2(logs/'01_all_trials_P1S_PLA.3mf',ROOT/'print'/'01_all_trials_P1S_PLA.3mf')
print('Slicing all trials',flush=True)
code,text=run_bambu.run([*common,'--slice','0','--export-3mf','02_all_trials_P1S_PLA_sliced.3mf',
    '--export-settings',str(logs/'effective_settings.json'),str(ROOT/'print'/'01_all_trials_P1S_PLA.3mf')],logs/'slice.log')
assert code==0,text[-3000:]
result=json.loads((logs/'result.json').read_text(encoding='utf-8'))
assert result['return_code']==0,result
shutil.copy2(logs/'02_all_trials_P1S_PLA_sliced.3mf',ROOT/'print'/'02_all_trials_P1S_PLA_sliced.3mf')
with zipfile.ZipFile(ROOT/'print'/'02_all_trials_P1S_PLA_sliced.3mf') as z:
    config=json.loads(z.read('Metadata/project_settings.config'))
    assert config['nozzle_diameter']==['0.4'] and config['filament_type']==['PLA']
    assert config['layer_height']=='0.12' and config['wall_generator']=='arachne'
    assert config['enable_support']=='0'
    for name in z.namelist():
        if name.startswith('Metadata/plate_1') and name.endswith('.png'):
            (ROOT/'verification'/Path(name).name).write_bytes(z.read(name))
summary={'slicer':'Bambu Studio 2.8.2.61','printer':'Bambu Lab P1S, 0.4 mm nozzle',
 'filament':'Generic PLA','layer_height_mm':.12,'initial_layer_height_mm':.2,
 'wall_generator':'arachne','wall_loops':4,'infill':'100% concentric','support':False,
 'printer_transmission_performed':False,'physical_print_performed':False,'result':result}
(ROOT/'verification'/'slicing.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
