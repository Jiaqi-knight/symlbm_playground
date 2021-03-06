import numpy
from string import Template

from simulation         import Lattice, Geometry
from utility.particles  import Particles
from symbolic.generator import LBM

import symbolic.D2Q9 as D2Q9

from OpenGL.GL   import *
from OpenGL.GLUT import *

from OpenGL.GL import shaders

from pyrr import matrix44

lattice_x = 512
lattice_y = 320

updates_per_frame = 40
particle_count    = 100000

inflow = 0.006
relaxation_time = 0.515

def circle(cx, cy, r):
    return lambda x, y: (x - cx)**2 + (y - cy)**2 < r*r

def get_channel_material_map(geometry):
    return [
        (lambda x, y: x > 0 and x < geometry.size_x-1 and y > 0 and y < geometry.size_y-1, 1), # bulk fluid
        (lambda x, y: y == 1,                 3), # inflow
        (lambda x, y: y == geometry.size_y-2, 4), # outflow
        (lambda x, y: x == 1,                 2), # bottom
        (lambda x, y: x == geometry.size_x-2, 2), # top
        (lambda x, y: y > geometry.size_y//20 and y < 2*geometry.size_y//20 and x < 4*geometry.size_x//9, 2),
        (lambda x, y: y > geometry.size_y//20 and y < 2*geometry.size_y//20 and x > 5*geometry.size_x//9, 2),
        (circle(geometry.size_x//2   , geometry.size_y//8, 3), 2),
        (circle(geometry.size_x//2-10, geometry.size_y//8, 3), 2),
        (circle(geometry.size_x//2+10, geometry.size_y//8, 3), 2),
        (lambda x, y: x == 0 or x == geometry.size_x-1 or y == 0 or y == geometry.size_y-1, 0) # ghost cells
    ]

boundary = Template("""
    if ( m == 2 ) {
        u_0 = 0.0;
        u_1 = 0.0;
    }
    if ( m == 3 ) {
        u_0 = 0.0;
        u_1 = min(time/10000.0 * $inflow, $inflow);
    }
    if ( m == 4 ) {
        rho = 1.0;
    }
""").substitute({
    'inflow': inflow
})

def get_projection(width, height):
    world_width = lattice_x
    world_height = world_width / width * height

    projection  = matrix44.create_orthogonal_projection(-world_width/2, world_width/2, -world_height/2, world_height/2, -1, 1)
    translation = matrix44.create_from_translation([-lattice_x/2, -lattice_y/2, 0])

    point_size = width / world_width

    return numpy.matmul(translation, projection), point_size

def glut_window(fullscreen = False):
    glutInit(sys.argv)
    glutInitDisplayMode(GLUT_RGBA | GLUT_DOUBLE | GLUT_DEPTH)

    if fullscreen:
        window = glutEnterGameMode()
    else:
        glutInitWindowSize(800, 600)
        glutInitWindowPosition(0, 0)
        window = glutCreateWindow("LBM")

    return window

lbm = LBM(D2Q9)

window = glut_window(fullscreen = False)

fragment_shader = shaders.compileShader("""
#version 430

in vec3 color;

void main(){
    gl_FragColor = vec4(color.xyz, 0.0);
}""", GL_FRAGMENT_SHADER)

particle_shader = shaders.compileShader(Template("""
#version 430

layout (location=0) in vec4 particles;

out vec3 color;

uniform mat4 projection;

vec3 fire(float x) {
    return mix(
        vec3(1.0, 1.0, 0.0),
        vec3(1.0, 0.0, 0.0),
        x
    );
}

void main() {
    gl_Position = projection * vec4(
        particles[0],
        particles[1],
        0.,
        1.
    );

    color = fire(1.0-particles[3]);
}""").substitute({
    'size_x': lattice_x,
    'size_y': lattice_y
}), GL_VERTEX_SHADER)

particle_program = shaders.compileProgram(particle_shader, fragment_shader)
projection_id = shaders.glGetUniformLocation(particle_program, 'projection')

lattice = Lattice(
    descriptor   = D2Q9,
    geometry     = Geometry(lattice_x, lattice_y),
    moments      = lbm.moments(optimize = False),
    collide      = lbm.bgk(f_eq = lbm.equilibrium(), tau = relaxation_time),
    boundary_src = boundary,
    opengl       = True
)

lattice.apply_material_map(
    get_channel_material_map(lattice.geometry))
lattice.sync_material()

particles = Particles(
    lattice,
    numpy.mgrid[
        4*lattice.geometry.size_x//9:5*lattice.geometry.size_x//9:particle_count/100j,
        lattice.geometry.size_y//20:2*lattice.geometry.size_y//20:100j,
    ].reshape(2,-1).T)

def on_display():
    for i in range(0,updates_per_frame):
        lattice.evolve()

    lattice.update_moments()

    for i in range(0,updates_per_frame):
        particles.update(aging = True)

    lattice.sync()

    glClear(GL_COLOR_BUFFER_BIT)

    shaders.glUseProgram(particle_program)
    glUniformMatrix4fv(projection_id, 1, False, numpy.ascontiguousarray(projection))
    particles.bind()
    glPointSize(point_size)
    glEnable(GL_POINT_SMOOTH)
    glDrawArrays(GL_POINTS, 0, particles.count)

    glutSwapBuffers()

def on_timer(t):
    glutTimerFunc(t, on_timer, t)
    glutPostRedisplay()

def on_reshape(width, height):
    global projection, point_size
    glViewport(0,0,width,height)
    projection, point_size = get_projection(width, height)

glutDisplayFunc(on_display)
glutReshapeFunc(on_reshape)
glutTimerFunc(10, on_timer, 10)

glutMainLoop()
