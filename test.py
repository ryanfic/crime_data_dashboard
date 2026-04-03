import matplotlib
matplotlib.use('Agg')

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
from matplotlib.collections import PatchCollection, LineCollection
from sklearn.decomposition import PCA
from sklearn.neighbors import kneighbors_graph
import gudhi
import os

# ── 1. Data ───────────────────────────────────────────────────────────────────
np.random.seed(42)
data = np.zeros((100, 3))
for i in range(100):
    g = i % 3
    if g == 0:
        data[i] = np.random.randn(3) * 0.3 + [1.2, 0.3, 0.3]
    elif g == 1:
        data[i] = np.random.randn(3) * 0.3 + [0.3, 1.2, 0.5]
    else:
        data[i] = np.random.randn(3) * 0.3 + [0.5, 0.5, 1.2]

norms = np.linalg.norm(data, axis=1)
pca = PCA(n_components=2)
pts2d = pca.fit_transform(data)

# ── 2. Simplex tree ───────────────────────────────────────────────────────────
st = gudhi.SimplexTree()
for i, v in enumerate(norms):
    st.insert([i], filtration=float(v))

G = kneighbors_graph(data, n_neighbors=6, mode='connectivity', include_self=False)
cx = G.tocoo()
for i, j in zip(cx.row, cx.col):
    st.insert([int(i), int(j)], filtration=float(max(norms[i], norms[j])))

G_dense = G.toarray()
for i in range(100):
    nbrs_i = set(np.where(G_dense[i] > 0)[0])
    for j in list(nbrs_i):
        nbrs_j = set(np.where(G_dense[int(j)] > 0)[0])
        for k in (nbrs_i & nbrs_j):
            tri = sorted([i, int(j), int(k)])
            st.insert(tri, filtration=float(max(norms[tri[0]],
                                                norms[tri[1]],
                                                norms[tri[2]])))

st.make_filtration_non_decreasing()
st.compute_persistence()

pairs = st.persistence()
print(f"{'Dim':<5} {'Birth':>10} {'Death':>10} {'Persistence':>12}")
print("-" * 42)
for dim, (birth, death) in pairs:
    pers = death - birth if np.isfinite(death) else float('inf')
    print(f"H{dim:<4} {birth:>10.4f} "
          f"{'∞' if not np.isfinite(death) else f'{death:>10.4f}'}"
          f"  {pers:>12.4f}")

# ── 3. Epsilon snapshots from actual events ───────────────────────────────────
key_events = sorted(set(
    [norms.min()]
    + [b for _, (b, d) in pairs if np.isfinite(b)]
    + [d for _, (b, d) in pairs if np.isfinite(d)]
    + [norms.max()]
))
n_panels = 5
indices = np.linspace(0, len(key_events) - 1, n_panels, dtype=int)
epsilons = [key_events[i] for i in indices]

def get_active(eps):
    verts, edges, tris = [], [], []
    for simplex, fval in st.get_filtration():
        if fval > eps + 1e-9:
            continue
        if len(simplex) == 1:
            verts.append(simplex[0])
        elif len(simplex) == 2:
            edges.append(simplex)
        elif len(simplex) == 3:
            tris.append(simplex)
    return verts, edges, tris

# ── 4. Main 2D plot ───────────────────────────────────────────────────────────
norm_min, norm_max = norms.min(), norms.max()
fig, axes = plt.subplots(1, n_panels, figsize=(20, 4.5))
fig.patch.set_facecolor('#f8f8f6')

for ax, eps in zip(axes, epsilons):
    ax.set_facecolor('#f0efe9')
    verts, edges, tris = get_active(eps)
    active_set = set(verts)

    patches = [Polygon(pts2d[t], closed=True) for t in tris]
    if patches:
        ax.add_collection(PatchCollection(
            patches, facecolor='#AFA9EC', edgecolor='none', alpha=0.40, zorder=1))

    segs = [[pts2d[e[0]], pts2d[e[1]]] for e in edges]
    if segs:
        ax.add_collection(LineCollection(
            segs, colors='#534AB7', linewidths=0.9, alpha=0.65, zorder=2))

    inactive = [i for i in range(len(data)) if i not in active_set]
    if inactive:
        ax.scatter(pts2d[inactive, 0], pts2d[inactive, 1],
                   c='#cccccc', s=12, zorder=3, linewidths=0)

    if verts:
        ax.scatter(pts2d[verts, 0], pts2d[verts, 1],
                   c=norms[verts], cmap='plasma',
                   vmin=norm_min, vmax=norm_max,
                   s=20, zorder=4, linewidths=0.4, edgecolors='white')

    b0 = st.persistent_betti_numbers(eps, eps)[0]
    b1 = st.persistent_betti_numbers(eps, eps)[1]
    ax.set_title(f'ε = {eps:.3f}\nβ₀={b0}  β₁={b1}', fontsize=9)
    ax.set_xlim(pts2d[:, 0].min() - 0.15, pts2d[:, 0].max() + 0.15)
    ax.set_ylim(pts2d[:, 1].min() - 0.15, pts2d[:, 1].max() + 0.15)
    ax.set_xticks([]); ax.set_yticks([])
    ax.text(0.02, 0.02, f'{len(verts)}v  {len(edges)}e  {len(tris)}f',
            transform=ax.transAxes, fontsize=7.5, color='#534AB7', va='bottom')

cbar_ax = fig.add_axes([0.92, 0.12, 0.012, 0.76])
sm = plt.cm.ScalarMappable(cmap='plasma',
     norm=plt.Normalize(vmin=norm_min, vmax=norm_max))
sm.set_array([])
cb = fig.colorbar(sm, cax=cbar_ax)
cb.set_label('√(a²+b²+c²)', fontsize=9)

fig.suptitle('Simplicial complex — sublevel filtration of √(a²+b²+c²)', fontsize=11)
fig.tight_layout(rect=[0, 0, 0.91, 1])

save_path = os.path.join(os.getcwd(), 'simplicial_complex_2d.png')
fig.savefig(save_path, dpi=150, bbox_inches='tight')
print(f"Saved: {save_path}")

# ── 5. Barcode ────────────────────────────────────────────────────────────────
fig2, ax2 = plt.subplots(figsize=(7, 3))
fig2.patch.set_facecolor('#f8f8f6')
ax2.set_facecolor('#f0efe9')

colors_dim = {0: '#534AB7', 1: '#1D9E75'}
finite_pairs = [(dim, b, d) for dim, (b, d) in pairs if np.isfinite(d)]
inf_pairs    = [(dim, b, d) for dim, (b, d) in pairs if not np.isfinite(d)]
all_plot = finite_pairs + [(dim, b, norm_max * 1.06) for dim, b, d in inf_pairs]
all_plot.sort(key=lambda x: (x[0], x[1]))

for idx, (dim, birth, death) in enumerate(all_plot):
    col = colors_dim.get(dim, '#888')
    ax2.plot([birth, death], [idx, idx],
             color=col, linewidth=3, solid_capstyle='butt', alpha=0.9)

from matplotlib.lines import Line2D
ax2.legend(handles=[
    Line2D([0],[0], color='#534AB7', linewidth=3, label='H0 (component)'),
    Line2D([0],[0], color='#1D9E75', linewidth=3, label='H1 (loop)'),
], fontsize=9, framealpha=0)
ax2.set_xlabel('√(a²+b²+c²)', fontsize=10)
ax2.set_ylabel('Feature index', fontsize=10)
ax2.set_title('Persistence barcode', fontsize=11)
fig2.tight_layout()

save_path2 = os.path.join(os.getcwd(), 'barcode.png')
fig2.savefig(save_path2, dpi=150, bbox_inches='tight')
print(f"Saved: {save_path2}")

# Auto-open on Mac
os.system(f'open "{save_path}"')
os.system(f'open "{save_path2}"')
