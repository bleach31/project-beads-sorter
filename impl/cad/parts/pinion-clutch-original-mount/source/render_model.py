from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw,ImageFont
import vtk
from vtk.util.numpy_support import vtk_to_numpy,numpy_to_vtk
import trimesh

ROOT=Path(__file__).resolve().parents[1]

def poly(mesh):
    pts=vtk.vtkPoints()
    pts.SetData(numpy_to_vtk(np.asarray(mesh.vertices),deep=True))
    cells=vtk.vtkCellArray()
    for f in mesh.faces:
        cells.InsertNextCell(3)
        for v in f: cells.InsertCellPoint(int(v))
    p=vtk.vtkPolyData();p.SetPoints(pts);p.SetPolys(cells)
    return p

def render(meshes,direction,up=(0,0,1),size=(900,750),zoom=1.0,target=None):
    ren=vtk.vtkRenderer();ren.SetBackground(0.955,0.967,0.978)
    for mesh,color,opacity in meshes:
        p=poly(mesh)
        n=vtk.vtkPolyDataNormals();n.SetInputData(p);n.SetFeatureAngle(35);n.SplittingOn();n.ConsistencyOn()
        mapper=vtk.vtkPolyDataMapper();mapper.SetInputConnection(n.GetOutputPort())
        a=vtk.vtkActor();a.SetMapper(mapper)
        prop=a.GetProperty();prop.SetColor(*color);prop.SetOpacity(opacity);prop.SetAmbient(.23);prop.SetDiffuse(.75);prop.SetSpecular(.2);prop.SetSpecularPower(25)
        ren.AddActor(a)
    cam=ren.GetActiveCamera()
    center=meshes[0][0].bounds.mean(axis=0) if target is None else np.array(target)
    d=np.array(direction,dtype=float);d/=np.linalg.norm(d)
    cam.SetPosition(*(center+d*150));cam.SetFocalPoint(*center);cam.SetViewUp(*up);cam.ParallelProjectionOn()
    win=vtk.vtkRenderWindow();win.SetOffScreenRendering(1);win.SetSize(*size);win.SetMultiSamples(8);win.AddRenderer(ren)
    ren.ResetCamera()
    if target is not None:
        cam.SetPosition(*(center+d*150));cam.SetFocalPoint(*center)
    cam.Zoom(zoom);ren.ResetCameraClippingRange();win.Render()
    cap=vtk.vtkWindowToImageFilter();cap.SetInput(win);cap.ReadFrontBufferOff();cap.Update()
    output=cap.GetOutput();arr=vtk_to_numpy(output.GetPointData().GetScalars()).reshape(size[1],size[0],-1)
    img=Image.fromarray(np.flipud(arr).copy());win.Finalize()
    return img

