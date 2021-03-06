import numpy
import time

import matplotlib
matplotlib.use('AGG')
import matplotlib.pyplot as plt

from simulation         import Lattice, Geometry
from symbolic.generator import LBM

import symbolic.D2Q9 as D2Q9

def MLUPS(cells, steps, time):
    return cells * steps / time * 1e-6

def generate_moment_plots(lattice, moments):
    for i, m in enumerate(moments):
        print("Generating plot %d of %d." % (i+1, len(moments)))

        velocity = numpy.ndarray(shape=tuple(reversed(lattice.geometry.inner_size())))
        for x, y in lattice.geometry.inner_cells():
            velocity[y-1,x-1] = numpy.sqrt(m[1,lattice.memory.gid(x,y)]**2 + m[2,lattice.memory.gid(x,y)]**2)

        plt.figure(figsize=(10, 10))
        plt.imshow(velocity, origin='lower', cmap=plt.get_cmap('seismic'))
        plt.savefig("result/implosion_%02d.png" % i, bbox_inches='tight', pad_inches=0)

def get_box_material_map(geometry):
    return [
        (lambda x, y: x > 0 and x < geometry.size_x-1 and y > 0 and y < geometry.size_y-1,  1), # bulk fluid
        (lambda x, y: x == 1 or y == 1 or x == geometry.size_x-2 or y == geometry.size_y-2, 2), # walls
        (lambda x, y: x == 0 or x == geometry.size_x-1 or y == 0 or y == geometry.size_y-1, 0)  # ghost cells
    ]

pop_eq = """
    if ( sqrt(pow(get_global_id(0) - ${geometry.size_x//2}.f, 2.f)
            + pow(get_global_id(1) - ${geometry.size_y//2}.f, 2.f)) < ${geometry.size_x//10} ) {
% for i, w_i in enumerate(descriptor.w):
        preshifted_f_next[${i*geometry.volume}] = 1./24.f;
        preshifted_f_prev[${i*geometry.volume}] = 1./24.f;
% endfor
    } else {
% for i, w_i in enumerate(descriptor.w):
        preshifted_f_next[${i*geometry.volume}] = ${w_i}.f;
        preshifted_f_prev[${i*geometry.volume}] = ${w_i}.f;
% endfor
}"""

boundary = """
    if ( m == 2 ) {
        u_0 = 0.0;
        u_1 = 0.0;
    }
"""

nUpdates = 2000
nStat    = 100

moments = []

print("Initializing simulation...\n")

lbm = LBM(D2Q9)

lattice = Lattice(
    descriptor = D2Q9,
    geometry   = Geometry(1024, 1024),

    layout = (32,1),

    moments = lbm.moments(optimize = False),
    collide = lbm.bgk(f_eq = lbm.equilibrium(), tau = 0.8),

    pop_eq_src   = pop_eq,
    boundary_src = boundary)

lattice.apply_material_map(
    get_box_material_map(lattice.geometry))
lattice.sync_material()

print("Starting simulation using %d cells...\n" % lattice.geometry.volume)

lastStat = time.time()

for i in range(1,nUpdates+1):
    lattice.evolve()

    if i % nStat == 0:
        lattice.sync()
        print("i = %4d; %3.0f MLUPS" % (i, MLUPS(lattice.geometry.volume, nStat, time.time() - lastStat)))
        moments.append(lattice.get_moments())
        lastStat = time.time()

print("\nConcluded simulation.\n")

generate_moment_plots(lattice, moments)
