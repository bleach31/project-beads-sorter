import math
import numpy as np
from PIL import Image
BG = "#f7f7f3"

def rgb(c):
    return tuple(bytes.fromhex(c.lstrip('#'))) if isinstance(c, str) else tuple(c)

def unpack(scene):
    vs = []
    fs = []
    cs = []
    n = 0
    for _, v, f, c in scene:
        vs.append(v)
        fs.append(f + n)
        cs.extend([c] * len(f))
        n += len(v)
    return (np.vstack(vs), np.vstack(fs), np.asarray(cs, float))

def basis(az, el):
    az, el = np.radians([az, el])
    right = np.array([-np.sin(az), np.cos(az), 0.0])
    eye = np.array([np.cos(el) * np.cos(az), np.cos(el) * np.sin(az), np.sin(el)])
    up = np.cross(eye, right)
    return np.stack([right, up, eye], axis=1)

def triangles_raster(projected, faces, width, height):
    for idx, tri in enumerate(faces):
        p = projected[tri]
        den = (p[1, 1] - p[2, 1]) * (p[0, 0] - p[2, 0]) + (p[2, 0] - p[1, 0]) * (p[0, 1] - p[2, 1])
        if abs(den) < 0.0001:
            continue
        xa = max(0, int(np.floor(p[:, 0].min())))
        xb = min(width - 1, int(np.ceil(p[:, 0].max())))
        ya = max(0, int(np.floor(p[:, 1].min())))
        yb = min(height - 1, int(np.ceil(p[:, 1].max())))
        if xa > xb or ya > yb:
            continue
        x, y = np.meshgrid(np.arange(xa, xb + 1) + 0.5, np.arange(ya, yb + 1) + 0.5)
        a = ((p[1, 1] - p[2, 1]) * (x - p[2, 0]) + (p[2, 0] - p[1, 0]) * (y - p[2, 1])) / den
        b = ((p[2, 1] - p[0, 1]) * (x - p[2, 0]) + (p[0, 0] - p[2, 0]) * (y - p[2, 1])) / den
        c = 1 - a - b
        z = a * p[0, 2] + b * p[1, 2] + c * p[2, 2]
        mask = (a >= -1e-07) & (b >= -1e-07) & (c >= -1e-07)
        if np.any(mask):
            yield (idx, xa, xb, ya, yb, a, b, c, z, mask)

def render(scene, w, h, az=-58, el=43, ss=1.4, shadows=True, pad=55):
    print('render', w, h, 'parts', len(scene), flush=True)
    W, H = (int(w * ss), int(h * ss))
    v, f, colors = unpack(scene)
    cam = basis(az, el)
    eye = cam[:, 2]
    center = (v.min(0) + v.max(0)) / 2
    p = (v - center) @ cam
    scale = min((W - pad * ss * 2) / np.ptp(p[:, 0]), (H - pad * ss * 2) / np.ptp(p[:, 1]))
    pc = (p.max(0) + p.min(0)) / 2
    p[:, 0] = (p[:, 0] - pc[0]) * scale + W / 2
    p[:, 1] = -(p[:, 1] - pc[1]) * scale + H / 2

    def project(q):
        q = (np.asarray(q) - center) @ cam
        return np.stack([(q[..., 0] - pc[0]) * scale / ss + w / 2, -(q[..., 1] - pc[1]) * scale / ss + h / 2], axis=-1)
    light = np.array([-0.55, -0.8, 1.65])
    light /= np.linalg.norm(light)
    fill = np.array([0.65, 0.4, 0.7])
    fill /= np.linalg.norm(fill)
    smat = basis(-124, 60)
    light = smat[:, 2]
    S = 1600
    q = v @ smat
    qmin = q.min(0)
    qmax = q.max(0)
    sscale = (S - 40) / max(np.ptp(q[:, 0]), np.ptp(q[:, 1]))
    qcenter = (qmax + qmin) / 2
    sq = q.copy()
    sq[:, 0] = (q[:, 0] - qcenter[0]) * sscale + S / 2
    sq[:, 1] = -(q[:, 1] - qcenter[1]) * sscale + S / 2
    sd = np.full((S, S), -np.inf, dtype=np.float32)
    if shadows:
        for idx, xa, xb, ya, yb, a, b, c, z, mask in triangles_raster(sq, f, S, S):
            buf = sd[ya:yb + 1, xa:xb + 1]
            mask &= z > buf
            buf[mask] = z[mask]

    def shadow_at(points):
        if not shadows:
            return np.ones(len(points))
        qq = points @ smat
        xx = np.rint((qq[:, 0] - qcenter[0]) * sscale + S / 2).astype(int)
        yy = np.rint(-(qq[:, 1] - qcenter[1]) * sscale + S / 2).astype(int)
        lit = np.zeros(len(points), float)
        for dx, dy in [(0, 0), (-2, 0), (2, 0), (0, 2), (0, -2)]:
            sx = np.clip(xx + dx, 0, S - 1)
            sy = np.clip(yy + dy, 0, S - 1)
            lit += qq[:, 2] + 0.7 >= sd[sy, sx]
        return lit / 5
    xx, yy = np.meshgrid(np.arange(W), np.arange(H))
    uu = (xx - W / 2) / scale + pc[0]
    vv = -(yy - H / 2) / scale + pc[1]
    ground = center + uu[..., None] * cam[:, 0] + vv[..., None] * cam[:, 1]
    travel = -ground[..., 2] / eye[2]
    ground += travel[..., None] * eye
    gshadow = shadow_at(ground.reshape(-1, 3)).reshape(H, W)
    from scipy.ndimage import gaussian_filter
    gshadow = gaussian_filter(gshadow, sigma=1.6 * ss)
    im = (np.array(rgb(BG))[None, None, :] * (0.87 + 0.13 * gshadow[..., None])).astype(np.uint8)
    depth = (ground - center) @ eye
    tri = v[f]
    normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    normals /= np.maximum(np.linalg.norm(normals, axis=1)[:, None], 1e-09)
    nl = np.clip(normals @ light, 0, 1)
    nf = np.clip(normals @ fill, 0, 1)
    for idx, xa, xb, ya, yb, a, b, c, z, mask in triangles_raster(p, f, W, H):
        buf = depth[ya:yb + 1, xa:xb + 1]
        mask &= z > buf + 1e-06
        if not np.any(mask):
            continue
        buf[mask] = z[mask]
        world = a[mask, None] * tri[idx, 0] + b[mask, None] * tri[idx, 1] + c[mask, None] * tri[idx, 2]
        lit = shadow_at(world)
        shade = 0.6 + 0.27 * nl[idx] * (0.28 + 0.72 * lit) + 0.13 * nf[idx]
        color = np.clip(colors[idx] * shade[:, None] + 3, 0, 255).astype(np.uint8)
        im[ya:yb + 1, xa:xb + 1][mask] = color
    out = Image.fromarray(im).resize((w, h), Image.Resampling.LANCZOS)
    print('render done', flush=True)
    return (out, project)
