"""Offline Bambu slicing for final feeder plate and a spare C rotor."""
from pathlib import Path
import sys,json,shutil,zipfile,hashlib,time,xml.etree.ElementTree as ET
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1];WS=ROOT.parent
sys.path.insert(0,str(WS/'.tools'))
import run_bambu as runner
runner.DATA=WS/'.tools/feeder_final_slicer_runtime'
NS={'c':'http://schemas.microsoft.com/3dmanufacturing/core/2015/02'}

def configure_objects(source,destination,overrides):
    with zipfile.ZipFile(source) as z:
        xml=ET.fromstring(z.read('Metadata/model_settings.config'));seen=set()
        for obj in xml.findall('object'):
            meta={e.get('key'):e for e in obj.findall('metadata') if e.get('key')}
            name=meta['name'].get('value');seen.add(name)
            for key,value in overrides[name].items():
                node=meta.get(key)
                if node is None:node=ET.SubElement(obj,'metadata',{'key':key})
                node.set('value',value)
        assert seen==set(overrides)
        encoded=ET.tostring(xml,encoding='utf-8',xml_declaration=True)
        with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as out:
            for item in z.infolist():out.writestr(item.filename,encoded if item.filename=='Metadata/model_settings.config' else z.read(item.filename))

def one(kind):
    stem='01_feeder' if kind=='feeder' else 'optional_rotor_C'
    base=ROOT/'slicer'/kind; settings=base/'settings';logs=base/'logs'
    for p in [settings,logs,ROOT/'print']:p.mkdir(parents=True,exist_ok=True)
    source=ROOT/'plates'/f'{stem}_geometry.3mf'
    # Keep the delivered effective input profiles with the package. Runtime and
    # official Bambu Studio binary are workspace tools, not redistributed here.
    for filename in ['machine.json','filament_pla.json','provenance.json','official_release.json','process.json']:
        assert (settings/filename).is_file(),f'Missing packaged profile: {settings/filename}'
    process=json.loads((settings/'process.json').read_text(encoding='utf-8'))
    with zipfile.ZipFile(source) as z:xml=ET.fromstring(z.read('3D/3dmodel.model'))
    names=[o.get('name') for o in xml.findall('c:resources/c:object',NS)]
    overrides={}
    for n in names:
        if n=='C_curved_rod':
            overrides[n]=dict(enable_support='1',support_type='tree(auto)',support_on_build_plate_only='1',brim_type='no_brim',brim_width='0',raft_layers='2',raft_expansion='8',raft_contact_distance='0.1',elefant_foot_compensation='0')
        else:overrides[n]=dict(enable_support='0',raft_layers='0',brim_type='outer_only',brim_width='2',elefant_foot_compensation='0.15')
    (settings/'process.json').write_text(json.dumps(process,indent=2),encoding='utf-8')
    (settings/'object_overrides.json').write_text(json.dumps(overrides,indent=2),encoding='utf-8')
    common=['--debug','3','--load-settings',str(settings/'machine.json')+';'+str(settings/'process.json'),'--load-filaments',str(settings/'filament_pla.json'),'--curr-bed-type','Textured PEI Plate','--arrange','0','--orient','0','--outputdir',str(logs)]
    print(stem,'NATIVE EXPORT',flush=True)
    code,text=runner.run([*common,'--export-3mf','native_base.3mf',str(source)],logs/'native_console.log');assert code==0,(code,text[-1500:])
    configured=ROOT/'print'/f'{stem}_P1S_PLA.3mf';sliced=ROOT/'print'/f'{stem}_P1S_PLA_sliced.3mf'
    configure_objects(logs/'native_base.3mf',configured,overrides)
    command=[*common,'--slice','0','--export-3mf',sliced.name,'--export-settings',str(logs/'effective_global_settings.json'),str(configured)]
    print(stem,'SLICE',flush=True);start=time.monotonic();code,text=runner.run(command,logs/'slice_console.log')
    result=json.loads((logs/'result.json').read_text(encoding='utf-8'))
    assert code==0 and result['return_code']==0,(code,text[-2500:])
    (logs/sliced.name).replace(sliced)
    with zipfile.ZipFile(sliced) as z:
        xml=ET.fromstring(z.read('Metadata/model_settings.config'));g=json.loads(z.read('Metadata/project_settings.config'))
    retained={}
    for o in xml.findall('object'):
        d={e.get('key'):e.get('value') for e in o.findall('metadata') if e.get('key')};retained[d['name']]={k:d.get(k) for k in overrides[d['name']]}
    assert retained==overrides,(retained,overrides)
    assert g['filament_type']==['PLA'] and g['nozzle_diameter']==['0.4'] and g['print_sequence']=='by layer'
    report=dict(slicer='Bambu Studio 2.8.2.61',printer='Bambu Lab P1S 0.4 nozzle',filament='Generic PLA',layer_height_mm=.16,initial_layer_height_mm=.2,wall_loops=4,infill='40% gyroid',top_bottom_layers=6,source=str(source.relative_to(ROOT)),source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),object_overrides=overrides,configured_project=str(configured.relative_to(ROOT)),sliced_project=str(sliced.relative_to(ROOT)),returncode=code,result=result,elapsed_seconds=time.monotonic()-start,settings_preserved=True,printer_transmission_performed=False,command=command)
    (base/'slice_summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(stem,json.dumps(result['sliced_plates'][0],ensure_ascii=False),flush=True)

if __name__=='__main__':
    for kind in (sys.argv[1:] or ['feeder','rotor']):one(kind)
