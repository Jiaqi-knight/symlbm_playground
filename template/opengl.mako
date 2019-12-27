<%
def gid():
    return {
        2: 'get_global_id(1)*%d + get_global_id(0)' % memory.size_x,
        3: 'get_global_id(2)*%d + get_global_id(1)*%d + get_global_id(0)' % (memory.size_x*memory.size_y, memory.size_x)
    }.get(descriptor.d)

def pop_offset(i):
    return i * memory.volume

def moments_cell():
    return {
        2: '(int2)(get_global_id(0), get_global_id(1))',
        3: '(int4)(get_global_id(0), get_global_id(1), get_global_id(2), 0)'
    }.get(descriptor.d)
%>

__kernel void collect_gl_moments(__global ${float_type}* f,
                                 __global int* material,
                                 __global float4* moments)
{
    const unsigned int gid = ${gid()};

    __global ${float_type}* preshifted_f = f + gid;

% for i in range(0,descriptor.q):
    const ${float_type} f_curr_${i} = preshifted_f[${pop_offset(i)}];
% endfor

% for i, expr in enumerate(moments_subexpr):
    const ${float_type} ${expr[0]} = ${ccode(expr[1])};
% endfor

    float4 data;

    if (material[gid] == 1) {
% if descriptor.d == 2:
      data.x = ${ccode(moments_assignment[0].rhs)};
      data.y = ${ccode(moments_assignment[1].rhs)};
      data.z = ${ccode(moments_assignment[2].rhs)};
      data.w = sqrt(data.y*data.y + data.z*data.z);
% elif descriptor.d == 3:
      data.x = ${ccode(moments_assignment[0].rhs)};
      data.y = ${ccode(moments_assignment[1].rhs)};
      data.z = ${ccode(moments_assignment[2].rhs)};
      data.w = ${ccode(moments_assignment[3].rhs)};
% endif
    } else {
      data.x = 0.0;
      data.y = 0.0;
      data.z = 0.0;
      data.w = -material[gid];
    }

    moments[gid] = data;
}

<%
def neighbor_offset(c_i):
    return {
        2: lambda:                                      c_i[1]*memory.size_x + c_i[0],
        3: lambda: c_i[2]*memory.size_x*memory.size_y + c_i[1]*memory.size_x + c_i[0]
    }.get(descriptor.d)()

%>

__kernel void collect_gl_moments_to_texture(__global ${float_type}* f,
                                            __global int* material,
% if descriptor.d == 2:
                                            __write_only image2d_t moments)
% elif descriptor.d == 3:
                                            __write_only image3d_t moments)
% endif
{
    const unsigned int gid = ${gid()};

    __global ${float_type}* preshifted_f = f + gid;

% for i in range(0,descriptor.q):
    const ${float_type} f_curr_${i} = preshifted_f[${pop_offset(i)}];
% endfor

% for i, expr in enumerate(moments_subexpr):
    const ${float_type} ${expr[0]} = ${ccode(expr[1])};
% endfor

    float4 data;

    if (material[gid] != 5) {
% if descriptor.d == 2:
      data.x = ${ccode(moments_assignment[0].rhs)};
      data.y = ${ccode(moments_assignment[1].rhs)};
      data.z = ${ccode(moments_assignment[2].rhs)};
      data.w = sqrt(data.y*data.y + data.z*data.z);
% elif descriptor.d == 3:
      data.x = ${ccode(moments_assignment[0].rhs)};
      data.y = ${ccode(moments_assignment[1].rhs)};
      data.z = ${ccode(moments_assignment[2].rhs)};
      data.w = ${ccode(moments_assignment[3].rhs)};
% endif
    } else {
      const int material_west  = material[gid + ${neighbor_offset((-1,0,0))}];
      const int material_east  = material[gid + ${neighbor_offset((1,0,0))}];
      const int material_north = material[gid + ${neighbor_offset((0,1,0))}];
      const int material_south = material[gid + ${neighbor_offset((0,-1,0))}];
      const int material_up    = material[gid + ${neighbor_offset((0,0, 1))}];
      const int material_down  = material[gid + ${neighbor_offset((0,0,-1))}];

      // recover surface normal approximation using surrounding materials
      float3 n;
      if (material_west  != 5) { n.x =  1; }
      if (material_east  != 5) { n.x = -1; }
      if (material_north != 5) { n.y = -1; }
      if (material_south != 5) { n.y =  1; }
      if (material_up    != 5) { n.z = -1; }
      if (material_down  != 5) { n.z =  1; }

      data.xyz = normalize(n);
      data.w   = 1.0; // signal impermeable material to raytracer
    }

    write_imagef(moments, ${moments_cell()}, data);
}