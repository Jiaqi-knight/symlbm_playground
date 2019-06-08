import pyopencl as cl
mf = cl.mem_flags

from string import Template

import numpy
import matplotlib.pyplot as plt

import time

kernel = """
float constant w[9] = {
    1./36., 1./9., 1./36.,
    1./9. , 4./9., 1./9. ,
    1./36 , 1./9., 1./36.
};

#define N_CELLS $nX*$nY

unsigned int indexOfDirection(int i, int j) {
    return (i+1) + 3*(1-j);
}

unsigned int indexOfCell(int x, int y)
{
    return y * $nX + x;
}

unsigned int idx(int x, int y, int i, int j) {
    return indexOfDirection(i,j)*N_CELLS + indexOfCell(x,y);
}

__global float f_i(__global __read_only float* f, int x, int y, int i, int j) {
    return f[idx(x,y,i,j)];
}

float comp(int i, int j, float2 v) {
    return i*v.x + j*v.y;
}

float sq(float x) {
    return x*x;
}

float f_eq(float w, float d, float2 v, int i, int j, float dotv) {
    return w * d * (1.f + 3.f*comp(i,j,v) + 4.5f*sq(comp(i,j,v)) - 1.5f*dotv);
}

__kernel void collide_and_stream(__global __write_only float* f_a,
                                 __global __read_only  float* f_b,
                                 __global __write_only float* moments,
                                 __global __read_only  int* material)
{
    const unsigned int gid = indexOfCell(get_global_id(0), get_global_id(1));

    const uint2 cell = (uint2)(get_global_id(0), get_global_id(1));

    const int m = material[gid];

    if ( m == 0 ) {
        return;
    }

    float f0 = f_i(f_b, cell.x+1, cell.y-1, -1, 1);
    float f1 = f_i(f_b, cell.x  , cell.y-1,  0, 1);
    float f2 = f_i(f_b, cell.x-1, cell.y-1,  1, 1);
    float f3 = f_i(f_b, cell.x+1, cell.y  , -1, 0);
    float f4 = f_i(f_b, cell.x  , cell.y  ,  0, 0);
    float f5 = f_i(f_b, cell.x-1, cell.y  ,  1, 0);
    float f6 = f_i(f_b, cell.x+1, cell.y+1, -1,-1);
    float f7 = f_i(f_b, cell.x  , cell.y+1,  0,-1);
    float f8 = f_i(f_b, cell.x-1, cell.y+1,  1,-1);

    const float d = f0 + f1 + f2 + f3 + f4 + f5 + f6 + f7 + f8;

    const float2 v = (float2)(
        (f5 - f3 + f2 - f6 + f8 - f0) / d,
        (f1 - f7 + f2 - f6 - f8 + f0) / d
    );
    const float dotv = dot(v,v);

    f0 = (1.0f - $tau) * f0 + $tau * f_eq(w[0], d,v,-1, 1, dotv);
    f1 = (1.0f - $tau) * f1 + $tau * f_eq(w[1], d,v, 0, 1, dotv);
    f2 = (1.0f - $tau) * f2 + $tau * f_eq(w[2], d,v, 1, 1, dotv);
    f3 = (1.0f - $tau) * f3 + $tau * f_eq(w[3], d,v,-1, 0, dotv);
    f4 = (1.0f - $tau) * f4 + $tau * f_eq(w[4], d,v, 0, 0, dotv);
    f5 = (1.0f - $tau) * f5 + $tau * f_eq(w[5], d,v, 1, 0, dotv);
    f6 = (1.0f - $tau) * f6 + $tau * f_eq(w[6], d,v,-1,-1, dotv);
    f7 = (1.0f - $tau) * f7 + $tau * f_eq(w[7], d,v, 0,-1, dotv);
    f8 = (1.0f - $tau) * f8 + $tau * f_eq(w[8], d,v, 1,-1, dotv);

    f_a[0*N_CELLS + gid] = f0;
    f_a[1*N_CELLS + gid] = f1;
    f_a[2*N_CELLS + gid] = f2;
    f_a[3*N_CELLS + gid] = f3;
    f_a[4*N_CELLS + gid] = f4;
    f_a[5*N_CELLS + gid] = f5;
    f_a[6*N_CELLS + gid] = f6;
    f_a[7*N_CELLS + gid] = f7;
    f_a[8*N_CELLS + gid] = f8;

    moments[1*gid] = d;
    moments[2*gid] = v.x;
    moments[3*gid] = v.y;
}"""

class D2Q9_BGK_Lattice:
    def idx(self, x, y):
        return y * self.nX + x;

    def __init__(self, nX, nY):
        self.nX = nX
        self.nY = nY
        self.nCells = nX * nY
        self.tick = True

        self.platform = cl.get_platforms()[0]
        self.context  = cl.Context(properties=[(cl.context_properties.PLATFORM, self.platform)])
        self.queue = cl.CommandQueue(self.context)

        self.np_pop_a = numpy.ndarray(shape=(9, self.nCells), dtype=numpy.float32)
        self.np_pop_b = numpy.ndarray(shape=(9, self.nCells), dtype=numpy.float32)

        self.np_moments  = numpy.ndarray(shape=(3, self.nCells), dtype=numpy.float32)
        self.np_material = numpy.ndarray(shape=(self.nCells, 1), dtype=numpy.int32)

        self.setup_geometry()

        self.equilibrilize()
        self.setup_anomaly()

        self.cl_pop_a = cl.Buffer(self.context, mf.READ_WRITE | mf.USE_HOST_PTR, hostbuf=self.np_pop_a)
        self.cl_pop_b = cl.Buffer(self.context, mf.READ_WRITE | mf.USE_HOST_PTR, hostbuf=self.np_pop_b)

        self.cl_material = cl.Buffer(self.context, mf.READ_ONLY  | mf.USE_HOST_PTR, hostbuf=self.np_material)
        self.cl_moments  = cl.Buffer(self.context, mf.READ_WRITE | mf.USE_HOST_PTR, hostbuf=self.np_moments)

        self.build_kernel()

    def setup_geometry(self):
        self.np_material[:] = 0
        for x in range(1,self.nX-1):
            for y in range(1,self.nY-1):
                if x == 1 or y == 1 or x == self.nX-2 or y == self.nY-2:
                    self.np_material[self.idx(x,y)] = -1
                else:
                    self.np_material[self.idx(x,y)] = 1

    def equilibrilize(self):
        self.np_pop_a[(0,2,6,8),:] = 1./36.
        self.np_pop_a[(1,3,5,7),:] = 1./9.
        self.np_pop_a[4,:] = 4./9.

        self.np_pop_b[(0,2,6,8),:] = 1./36.
        self.np_pop_b[(1,3,5,7),:] = 1./9.
        self.np_pop_b[4,:] = 4./9.

    def setup_anomaly(self):
        bubbles = [ [        self.nX//4,        self.nY//4],
                    [        self.nX//4,self.nY-self.nY//4],
                    [self.nX-self.nX//4,        self.nY//4],
                    [self.nX-self.nX//4,self.nY-self.nY//4] ]

        for x in range(0,self.nX-1):
            for y in range(0,self.nY-1):
                for [a,b] in bubbles:
                    if numpy.sqrt((x-a)*(x-a)+(y-b)*(y-b)) < self.nX//10:
                        self.np_pop_a[:,self.idx(x,y)] = 1./24.
                        self.np_pop_b[:,self.idx(x,y)] = 1./24.

    def build_kernel(self):
        self.program = cl.Program(self.context, Template(kernel).substitute({
            'nX' : self.nX,
            'nY' : self.nY,
            'tau': "0.56f"
        })).build() #'-cl-single-precision-constant -cl-fast-relaxed-math')

    def evolve(self):
        if self.tick:
            self.tick = False
            self.program.collide_and_stream(self.queue, (self.nX,self.nY), (64,1), self.cl_pop_a, self.cl_pop_b, self.cl_moments, self.cl_material)
        else:
            self.tick = True
            self.program.collide_and_stream(self.queue, (self.nX,self.nY), (64,1), self.cl_pop_b, self.cl_pop_a, self.cl_moments, self.cl_material)

    def sync(self):
        self.queue.finish()

    def show(self, i):
        cl.enqueue_copy(LBM.queue, LBM.np_moments, LBM.cl_moments).wait();

        density = numpy.ndarray(shape=(self.nX-2, self.nY-2))
        for y in range(1,self.nY-1):
            for x in range(1,self.nX-1):
                density[x-1,y-1] = self.np_moments[0,self.idx(x,y)]

        plt.imshow(density, vmin=0.2, vmax=2.0, cmap=plt.get_cmap("seismic"))
        plt.savefig("result/density_" + str(i) + ".png")


def MLUPS(cells, steps, time):
    return cells * steps / time * 1e-6

nUpdates = 1000
nStat = 100

print("Initializing simulation...\n")

LBM = D2Q9_BGK_Lattice(1024, 1024)

print("Starting simulation using %d cells...\n" % LBM.nCells)

lastStat = time.time()

for i in range(1,nUpdates+1):
    if i % nStat == 0:
        LBM.sync()
        print("i = %4d; %3.0f MLUPS" % (i, MLUPS(LBM.nCells, nStat, time.time() - lastStat)))
        lastStat = time.time()

    LBM.evolve()

LBM.show(nUpdates)
