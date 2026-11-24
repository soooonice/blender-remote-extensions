# SPDX-License-Identifier: GPL-3.0-or-later
from .browser_data import FILTER_ICONS
from .browser_data import GROUPS
from .browser_data import OBJECT_GROUPS
from .browser_data import R
from .browser_data import TREE
from .browser_data import akey
from .browser_data import children
from .browser_data import content_entries
from .browser_data import current
from .browser_data import group_folder
from .browser_data import resolve
from .browser_data import root_modifier
from .browser_data import tree_rows
from .browser_data import view
from .previews import enqueue
from .previews import mesh_wire
from .previews import native_texture
from .previews import raster_thumbnail
from bpy.props import BoolProperty
from bpy.props import EnumProperty
from bpy.props import IntProperty
from bpy.props import StringProperty
from functools import lru_cache
from gpu_extras.batch import batch_for_shader
from gpu_extras.presets import draw_texture_2d
import blf
import bpy
import gpu
import math
import os


def quad(x, y, w, h, color):
    if not hasattr(R,'quad_gpu'):
        shader=gpu.shader.from_builtin('UNIFORM_COLOR')
        batch=batch_for_shader(shader,'TRI_FAN',{'pos':[(0,0),(1,0),(1,1),(0,1)]})
        R.quad_gpu=shader,batch
    shader,batch=R.quad_gpu
    with gpu.matrix.push_pop():
        gpu.matrix.translate((x,y,0))
        gpu.matrix.scale((w,h,1))
        shader.bind()
        shader.uniform_float('color',color)
        batch.draw(shader)


def lines(points, color=(.55,.78,.95,1)):
    if not points: return
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    shader.bind()
    shader.uniform_float('color', color)
    batch_for_shader(shader, 'LINES', {'pos': points}).draw(shader)


def text(x, y, value, size=12, color=(.85,.87,.90,1), width=None):
    blf.size(0, size)
    value = str(value)
    if width is not None:
        while value and blf.dimensions(0, value)[0] > width:
            value = value[:-2] + '…' if len(value) > 2 else ''
    blf.position(0, x, y, 0)
    blf.color(0, *color)
    blf.draw(0, value)


SHIELD_RGBA = ('c%1E&%N2t#5X91d2UKe+;03&&*<I@}$ABc8thIiNF~;(CJxtA|bf4bfpZDYrU)`rPc<VQ@!;a5{2G+CedKbL8J9UWUtll7luWEyArYa4T=b^p}>h~)d)ZR*-YVO%w72UJgD!WHBc5shmJ=wpLdjxYgcTet)XYa}0)!mE#WdF{0-@~E1yVV1K{7?0t@ZV=~!5@G8@y8#3{PD+M?}0!5_~Wng@6yAA{mnDfT_PDR&yMPm&E)w$ONS~PUVQ53R{1s~ep_*0Jf=ABp6f*K-41F_Wdk*zvVodQ)j`d{7&~w`l@)Mw', 'c%1E(!4AVP2*vjQKb?s~E>$P3Enq0m62~Rjs<O4#XK6GVP2T*1-ivg9dxNXc`;zW&Y2XFzLArNq5Do1|c^{#DN%sxyO}cL;yKkm?AL-y8-LjK=rv}mccvHondRMx+S8YJt?Fr#eHTT{n`@U)ovhIm)(9xZ45Pf!bgDU<Wzq><)Z$Eo4&pn@>OYD_-&y(}AzJcgFh&LqS4vOdomEAXVg9=18=-_WeHIRP~e<PwnCx64cK{tP6y1y~q-<a-iOnd*%nDYM@f&Aq!fBDN_{?i)#<9=nT;O$kp3GGL;pgpJ#^xjkldQY+ey&u_t-izu$@1fCX2F@2^kww4')


META_COLOR=(.55,.58,.62,1)


CARD_FOOTER=42


def draw_shield(enabled,x,y,size):
    import base64,zlib
    if not hasattr(R,'shield_textures'): R.shield_textures={}
    if enabled not in R.shield_textures:
        pixels=zlib.decompress(base64.b85decode(SHIELD_RGBA[int(enabled)]))
        buf=gpu.types.Buffer('FLOAT',len(pixels),[v/255 if i%4==3 else META_COLOR[i%4] for i,v in enumerate(pixels)])
        R.shield_textures[enabled]=gpu.types.GPUTexture((64,64),format='RGBA32F',data=buf)
    gpu.state.blend_set('ALPHA')
    draw_texture_2d(R.shield_textures[enabled],(x,y),size,size)


@lru_cache(maxsize=1024)
def name_lines(name,size,width):
    blf.size(0,size)
    def fit(value,suffix):
        lo,hi=0,len(value)
        while lo<hi:
            mid=(lo+hi+1)//2
            if blf.dimensions(0,value[:mid]+suffix)[0]<=width: lo=mid
            else: hi=mid-1
        return lo
    first=fit(name,'')
    if first==len(name): return (name,)
    split=name.rfind(' ',0,first+1)
    if split<=0: split=max(1,first)
    tail=name[split:].lstrip()
    if blf.dimensions(0,tail)[0]>width:
        tail=tail[:fit(tail,'…')]+'…'
    return name[:split].rstrip(),tail


def draw_card_name(name,x,y,width,scale,color):
    size=11*scale
    rows=name_lines(name,size,width-12*scale)
    blf.size(0,size)
    baseline=y+(23 if len(rows)==1 else 30)*scale
    for i,line in enumerate(rows):
        left=x+(width-blf.dimensions(0,line)[0])*.5
        text(left,baseline-i*13*scale,line,size,color)


@lru_cache(maxsize=4)
def light_segments(kind):
    points=[]
    def stroke(*vertices):
        for a,b in zip(vertices,vertices[1:]): points.extend((a,b))
    def ellipse(cx,cy,rx,ry):
        stroke(*[(cx+rx*math.cos(i*math.tau/24),cy+ry*math.sin(i*math.tau/24)) for i in range(25)])
    if kind=='SPOT':
        stroke((-.33,-.28),(0,.40),(.33,-.28))
        ellipse(0,-.28,.33,.075)
    elif kind=='AREA':
        stroke((-.38,.16),(.18,.34),(.38,-.04),(-.18,-.23),(-.38,.16))
        stroke((0,.06),(.08,-.38))
    elif kind=='SUN':
        ellipse(0,0,.21,.21)
        for i in range(8):
            a=i*math.tau/8
            stroke((.28*math.cos(a),.28*math.sin(a)),(.44*math.cos(a),.44*math.sin(a)))
    else:
        ellipse(0,0,.32,.32)
        ellipse(0,0,.12,.32)
        ellipse(0,0,.32,.10)
    return points


def draw_group_card(group,parent,x,y,size):
    node=next((n for n in getattr(parent,'nodes',()) if getattr(n,'node_tree',None)==group),None)
    sockets=[s for s in group.interface.items_tree if s.item_type=='SOCKET' and not getattr(s,'hide_in_modifier',False)]
    sockets.sort(key=lambda s:s.in_out!='OUTPUT')
    row=size/max(7,min(12,len(sockets))+2)
    left=x+size*.05
    width=size*.90
    top=y+size*.92
    quad(left,top-row*(1+min(12,len(sockets))),width,row*(1+min(12,len(sockets))),(.10,.10,.10,1))
    quad(left,top-row,width,row,(.34,.15,.06,1))
    text(left+4,top-row*.78,(node.label if node and node.label else group.name),max(7,row*.60),width=width-8)
    for i,socket in enumerate(sockets[:12]):
        out=socket.in_out=='OUTPUT'
        label=socket.name
        value=node.inputs.get(socket.identifier) if node and not out else None
        default=getattr(value or socket,'default_value',None)
        if not out and not getattr(value,'is_linked',False) and isinstance(default,(float,int)):
            label+=f'  {default:.2f}'
        cy=top-row*(i+1.55)
        text(left+(width*.38 if out else 5),cy-row*.2,label,max(6,row*.52),width=width*(.59 if out else .90))
        color={'NodeSocketVector':(.32,.36,.8,1),'NodeSocketColor':(.8,.68,.18,1),'NodeSocketGeometry':(.18,.65,.51,1)}.get(socket.socket_type,(.55,.55,.55,1))
        quad(left+(width-2 if out else -2),cy-2,4,4,color)


def thumbnail(item, x, y, size, ancestors=()):
    parent=resolve(ancestors[-1]) if ancestors else None
    data=item.data if isinstance(item,bpy.types.Object) else item
    glyph=isinstance(data,(bpy.types.Armature,bpy.types.Light,bpy.types.VectorFont,bpy.types.Palette,bpy.types.Action,bpy.types.Collection,bpy.types.Scene))
    glyph|=isinstance(item,bpy.types.GeometryNodeTree) and not root_modifier(parent,item)
    key=(parent.session_uid,item.session_uid) if parent and isinstance(item,bpy.types.GeometryNodeTree) else item.session_uid
    if glyph:
        if key not in R.glyphs:
            R.glyphs[key]=raster_thumbnail((128,128),lambda w,h:draw_thumbnail_content(item,0,0,w,ancestors))
            if len(R.glyphs)>512: R.glyphs.pop(next(iter(R.glyphs)))
        draw_texture_2d(R.glyphs[key],(x,y),size,size)
        return
    draw_thumbnail_content(item,x,y,size,ancestors)


def draw_thumbnail_content(item,x,y,size,ancestors):
    if isinstance(item,bpy.types.Palette):
        colors = list(item.colors)
        n = max(1, math.ceil(math.sqrt(len(colors))))
        cell = size*.8/n
        for i,c in enumerate(colors):
            quad(x+size*.1+(i%n)*cell,y+size*.9-(1+i//n)*cell,max(.3,cell-1),max(.3,cell-1),(*c.color,1))
        if not colors: text(x+8,y+size*.5,'Empty palette',10,width=size-16)
        return
    parent=resolve(ancestors[-1]) if ancestors else None
    if isinstance(item,(bpy.types.GeometryNodeTree,bpy.types.ShaderNodeTree)):
        if isinstance(item,bpy.types.GeometryNodeTree):
            if not root_modifier(parent,item):
                draw_group_card(item,parent,x,y,size)
                return
            key=(ancestors[0],parent.session_uid,item.session_uid) if ancestors and isinstance(resolve(ancestors[0]),bpy.types.Scene) else (parent.session_uid,item.session_uid)
        else:
            context_ids=tuple(uid for uid in ancestors if isinstance(resolve(uid),(bpy.types.Material,bpy.types.ShaderNodeTree)))
            key=(*context_ids,item.session_uid)
        if key not in R.attempted:
            R.attempted.add(key)
            R.queue.append(key)
        tex,_,_=native_texture(item,key)
        if tex:
            blend=gpu.state.blend_get()
            gpu.state.blend_set('ALPHA')
            try: draw_texture_2d(tex,(x,y),size,size,is_scene_linear_with_rec709_srgb_target=True)
            finally: gpu.state.blend_set(blend)
        else: text(x+4,y+size*.48,item.name,11,width=size-8)
        return
    if isinstance(item, (bpy.types.Scene, bpy.types.Collection)):
        color = (.35,.35,.35,1) if isinstance(item,bpy.types.Scene) else (.40,.57,.72,1)
        quad(x+size*.10,y+size*.19,size*.80,size*.57,color)
        quad(x+size*.10,y+size*.72,size*.33,size*.12,color)
        return
    if isinstance(item,(bpy.types.NodeTree,bpy.types.Action)):
        key=item.session_uid
        if key not in R.cards:
            if isinstance(item,bpy.types.NodeTree):
                sockets=[s.in_out for s in item.interface.items_tree if s.item_type=='SOCKET']
                R.cards[key]=(item.bl_label,f"{sockets.count('INPUT')} in / {sockets.count('OUTPUT')} out",())
            else:
                lo,hi=item.frame_range
                bins=set()
                for layer in item.layers:
                    for strip in layer.strips:
                        for bag in getattr(strip,'channelbags',()):
                            for curve in bag.fcurves:
                                for point in curve.keyframe_points:
                                    bins.add(round(64*max(0,min(1,(point.co.x-lo)/max(hi-lo,1)))))
                R.cards[key]=('Action',f'{lo:g} - {hi:g}',sorted(bins))
        title,label,bins=R.cards[key]
        if not isinstance(item,bpy.types.Action): text(x+4,y+size*.65,title,12,width=size-8)
        text(x+4,y+size*.22,label,11,width=size-8)
        if bins:
            lines([(x+size*(.08+.84*i/64),y+size*h) for i in bins for h in (.41,.54)],(.55,.76,.95,1))
        return
    if isinstance(item,bpy.types.VectorFont):
        path=bpy.path.abspath(item.filepath,library=item.library)
        if path not in R.font_cache:
            R.font_cache[path]=blf.load(path) if path and item.filepath!='<builtin>' and os.path.isfile(path) else -1
        font=R.font_cache[path]
        if font<0 and item.filepath!='<builtin>':
            text(x+4,y+size*.45,item.name,12,width=size-8)
            return
        font=max(0,font)
        sample='Ag 012'
        blf.size(font,max(8,int(size*.20)))
        w,h=blf.dimensions(font,sample)
        blf.position(font,x+(size-w)/2,y+(size-h)/2,0)
        blf.color(font,.86,.86,.86,1)
        blf.draw(font,sample)
        return
    arm=item.data if isinstance(item,bpy.types.Object) else item
    if isinstance(arm,bpy.types.Armature):
        bones=item.pose.bones if isinstance(item,bpy.types.Object) and item.pose else arm.bones
        faces=[]
        for bone in bones:
            head,tail=(bone.head,bone.tail) if isinstance(bone,bpy.types.PoseBone) else (bone.head_local,bone.tail_local)
            axis=tail-head
            if axis.length<1e-8: continue
            u=axis.orthogonal().normalized()*axis.length*.11
            v=axis.normalized().cross(u)
            mid=head+axis*.18
            ring=[mid+u,mid+v,mid-u,mid-v]
            for i in range(4):
                faces.extend([(head,ring[i],ring[i-1]),(tail,ring[i-1],ring[i])])
        if faces:
            projected=[(.8*q.x-.6*q.y,.3*q.x+.4*q.y+.85*q.z) for f in faces for q in f]
            xs,ys=zip(*projected)
            cx=(min(xs)+max(xs))/2; cy=(min(ys)+max(ys))/2
            k=size*.88/max(max(xs)-min(xs),max(ys)-min(ys),1e-7)
            shader=gpu.shader.from_builtin('SMOOTH_COLOR')
            pts=[(x+size/2+(a-cx)*k,y+size/2+(b-cy)*k) for a,b in projected]
            colors=[(.38+.12*((i//6)%4),.54+.09*((i//6)%4),.72+.06*((i//6)%4),1) for i in range(len(pts))]
            batch_for_shader(shader,'TRIS',{'pos':pts,'color':colors}).draw(shader)
        return
    light=item.data if isinstance(item,bpy.types.Object) else item
    if isinstance(light,bpy.types.Light):
        glyph=light_segments(light.type)
        lines([(x+size*(.5+.56*a),y+size*(.5+.56*b)) for a,b in glyph],(.95,.76,.35,1))
        return
    preview_key=None
    if isinstance(item,bpy.types.Object) and item.type in {'CURVE','FONT','MESH'}:
        scene=resolve(ancestors[0]) if ancestors else None
        if not isinstance(scene,bpy.types.Scene) or scene.objects.get(item.name)!=item:
            scene=bpy.context.scene
            if not scene or scene.objects.get(item.name)!=item:
                scene=next(iter(item.users_scene),None)
        if scene:
            preview_key=(scene.session_uid,item.session_uid)
            if preview_key not in R.attempted:
                R.attempted.add(preview_key)
                R.queue.append(preview_key)
    if (preview_key or item.session_uid) in R.curve_lines:
        points=R.curve_lines[preview_key or item.session_uid]
        if points:
            line_key=preview_key or item.session_uid
            if line_key not in R.glyphs:
                R.glyphs[line_key]=raster_thumbnail((128,128),lambda w,h:lines([(w*(.07+.86*a),h*(.07+.86*b)) for a,b in points],(1.0,.37,.06,1.0)))
            draw_texture_2d(R.glyphs[line_key],(x,y),size,size)
        return
    if preview_key is None and isinstance(item,(bpy.types.Curve,bpy.types.Object,bpy.types.Material,bpy.types.World)): enqueue(item)
    tex, aspect, linear = native_texture(item,preview_key)
    if tex:
        w,h = (size,size/aspect) if aspect >= 1 else (size*aspect,size)
        gpu.state.blend_set('ALPHA_PREMULT' if not linear else 'ALPHA')
        draw_texture_2d(tex,(x+(size-w)/2,y+(size-h)/2),w,h,
                        is_scene_linear_with_rec709_srgb_target=linear)
        gpu.state.blend_set('ALPHA')
        return
    data = item.data if isinstance(item,bpy.types.Object) else item
    if isinstance(data,bpy.types.Armature):
        points=[(.8*p.x-.6*p.y,.3*p.x+.4*p.y+.85*p.z) for b in data.bones for p in (b.head_local,b.tail_local)]
        if points:
            xs,ys=zip(*points)
            span=max(max(xs)-min(xs),max(ys)-min(ys),.00001)
            lines([(x+size*(.5+.88*(a-(min(xs)+max(xs))/2)/span),y+size*(.5+.88*(b-(min(ys)+max(ys))/2)/span)) for a,b in points])
        else: text(x+6,y+size*.5,'Armature',12)
        return
    if isinstance(data,bpy.types.Mesh):
        lines([(x+size*(.08+.84*a),y+size*(.08+.84*b)) for a,b in mesh_wire(data)])
        return
    if isinstance(data,bpy.types.Camera):
        coords = [(0.12,.30),(.65,.30),(.65,.30),(.65,.70),(.65,.70),(.12,.70),
                  (.12,.70),(.12,.30),(.65,.50),(.92,.76),(.92,.76),(.92,.24),(.92,.24),(.65,.50)]
        lines([(x+a*size,y+b*size) for a,b in coords],(.55,.82,.67,1))
        text(x+8,y+5,f'{data.lens:g} mm',10,width=size-16)
        return
    # Every other ID gets a readable, type-specific information card.
    kind = data.bl_rna.identifier if data else item.bl_rna.identifier
    # Transparent information glyph: no backing rectangle.
    text(x+size*.23,y+size*.50,kind[:4].upper(),max(14,int(size*.19)),width=size*.60)
    text(x+size*.18,y+size*.25,kind,10,width=size*.65)


DEFAULT_TILE_SIZE=140


def geometry(width, height, scale, v):
    sidebar = min(210*scale,max(120*scale,width*.20)) if width>360*scale else 0
    sidebar=min(width*.65,v.get('width',sidebar/scale)*scale) if not v.get('hidden') else 0
    tile = v.get('tile_size',DEFAULT_TILE_SIZE)*scale
    gap = 10*scale
    start = sidebar+gap
    columns = max(1,int((width-start)/(tile+gap)))
    return sidebar,tile,gap,start,columns


def slot_layout(parent,entries):
    rows=[(item.session_uid,path) for item,path in entries]
    if not isinstance(parent,bpy.types.Object): return rows,{}
    direct={uid for uid,path in rows if len(path)==1 and isinstance(resolve(uid),bpy.types.Material)}
    ordered=[]
    slots={}
    for index,slot in enumerate(parent.material_slots):
        if slot.material and slot.material.session_uid in direct:
            uid=slot.material.session_uid
            slots[len(ordered)]=(parent.session_uid,index,uid)
            ordered.append((uid,(uid,)))
    ordered.extend((uid,path) for uid,path in rows if uid not in direct or len(path)!=1)
    return ordered,slots


def draw():
    context=bpy.context
    v=view(context)
    if not v or context.region.type!='WINDOW': return
    region=context.region
    w,h=region.width,region.height
    scale=context.preferences.system.ui_scale
    sidebar,tile,gap,start,columns=geometry(w,h,scale,v)
    top=h-8*scale; bottom=26*scale
    v['region']=(region.x,region.y,w,h)
    v['hits']=[]
    # Background belongs to Blender. Only draw selected tile highlights.
    theme=context.preferences.themes[0]
    fg=(*theme.user_interface.wcol_regular.text[:3],1)
    if max(fg[:3])<.1: fg=(.85,.85,.85,1)
    gpu.state.blend_set('ALPHA')
    try:
        def hit(rect,kind,payload): v['hits'].append((rect,kind,payload))
        # These left-hand hit rectangles are ONLY for an in-flight drop;
        # ordinary clicks are routed to real native operator buttons.
        rowh=26*scale
        for i,(name,path,uid,depth) in enumerate(tree_rows(v) if sidebar else ()):
            # Properties reserves a context breadcrumb above native panels.
            _,y=region.view2d.view_to_region(0,-45*scale-(i+1)*rowh,clip=False)
            if y>=bottom:
                hit((8*scale,y,max(0,sidebar-16*scale),rowh),'tree',(uid,path))
        # Mask the host breadcrumb's right-hand pin before painting our tiles.
        background=context.preferences.themes[0].properties.space.back
        quad(w-44*scale,h-42*scale,44*scale,42*scale,(*background[:3],1))
        if sidebar: quad(0,0,sidebar,h,(0,0,0,.09))
        state=ui_state(context)
        key=(tuple(v['path']),v.get('pin_contents',False),v.get('browse_result',False),state.expanded,state.scope,state.query,
             tuple(getattr(state,'filter_'+g) for g in GROUPS),R.last_index)
        if v.get('layout_key')!=key:
            entries=((item,(item.session_uid,)) for item in children(current(v)) if not isinstance(item,(bpy.types.Palette,bpy.types.VectorFont))) if not (state.filter_Palette or state.filter_Fonts) and v.get('pin_contents') and not (state.expanded or state.query.strip()) else content_entries(current(v),state,v.get('browse_result',False))
            v['entries'],v['slot_rows']=slot_layout(current(v),entries)
            v['layout_key']=key
            v.pop('position_columns',None)
        if v.get('position_columns')!=columns:
            v['positions']=[(*divmod(index,columns),uid,path) for index,(uid,path) in enumerate(v['entries'])]
            v['position_columns']=columns
        positions=v['positions']
        v['max_x']=v['offset_x']=0
        v['tile_paths']=[]
        v['slot_hits']={}
        rowh=tile+CARD_FOOTER*scale
        rows=positions[-1][0]+1 if positions else 0
        v['max_scroll']=max(0,rows*rowh-(top-bottom))
        focus=v.pop('scroll_to',0)
        if focus:
            row=next((row for row,col,uid,path in positions if uid==focus),0)
            v['scroll']=max(0,(row+1)*rowh-(top-bottom))
        v['scroll']=min(v['scroll'],v['max_scroll'])
        first=max(0,int(v['scroll']//rowh)*columns)
        end=first+(math.ceil(h/rowh)+2)*columns
        v['clip']=(bottom,top)
        previous=gpu.state.scissor_get()
        ox,oy,_,_=gpu.state.viewport_get()
        gpu.state.scissor_set(int(ox+start),int(oy+bottom),max(1,int(w-start)),max(1,int(top-bottom)))
        gpu.state.scissor_test_set(True)
        try:
            for row,col,uid,path in positions[first:end]:
                item=resolve(uid)
                if item is None: continue
                x=start+col*(tile+gap)-v['offset_x']
                if x+tile<=start or x>=w: continue
                y=top-(row+1)*rowh+v['scroll']+gap
                if y+rowh-gap<=bottom or y>=top: continue
                ref=v['slot_rows'].get(row*columns+col)
                if ref: v['slot_hits'][x,y,tile,rowh-gap]=ref
                if (ref in v.get('slot_selection',()) if ref else uid==v['selected'] or uid in v.get('multi',())):
                    quad(x,y,tile,rowh-gap,tuple(background[j]*.72+(.24,.45,.70)[j]*.28 for j in range(3))+(1,))
                thumbnail(item,x+6*scale,y+41*scale,tile-12*scale,tuple(v['path'])+tuple(path[:-1]))
                draw_card_name(item.name,x,y,tile,scale,fg)
                hit((x,y,tile,rowh-gap),'tile',item.session_uid)
                v['tile_paths'].append((x,y,tile,rowh-gap,path))
                if isinstance(item,(bpy.types.Material,bpy.types.Image)) or group_folder(item,resolve(path[-2]) if len(path)>1 else current(v)):
                    ex=x+tile-23*scale; ey=y+rowh-gap-22*scale
                    if isinstance(item,(bpy.types.ShaderNodeTree,bpy.types.Image)):
                        quad(ex,ey,21*scale,21*scale,(.075,.075,.075,.96))
                    text(ex+3*scale,ey+4*scale,'✎',15*scale,(.94,.94,.94,1))
                    hit((ex,ey,22*scale,22*scale),'edit',item.session_uid)
                sx=x+tile-17*scale
                count=str(item.users)
                blf.size(0,9*scale)
                count_x=sx-3*scale-blf.dimensions(0,count)[0]
                draw_type_icons(item,x+6*scale,y+2*scale,scale)
                text(count_x,y+4*scale,count,9*scale,META_COLOR)
                draw_shield(item.use_fake_user,sx,y+2*scale,12*scale)
                hit((sx-2*scale,y,16*scale,16*scale),'shield',item.session_uid)
        finally:
            gpu.state.scissor_set(*previous)
            gpu.state.scissor_test_set(False)
        if v.get('box'):
            ax,ay,bx,by=v['box']
            left,right=sorted((ax,bx)); low,high=sorted((ay,by))
            color=(.385,.56,.70,1)
            for rect in ((left,low,right-left,1),(left,high-1,right-left,1),
                         (left,low,1,high-low),(right-1,low,1,high-low)):
                quad(*rect,color)
        if not positions: text(start+12,top-35,'No items',12,fg)
        text(start,9*scale,R.message or f'{len(positions)} items | Double-click: open | Drag: viewport / collection',10*scale,fg,width=w-start-8)
    finally:
        gpu.state.blend_set('NONE')


def ui_state(context,browser=None):
    key=next((key for key,value in R.views.items() if value is browser),None) if browser is not None else None
    if key is None:
        if context.window is None or context.area is None: return None
        key=akey(context.window,context.area)
    key=str(key)
    states=context.window_manager.scb_ui_states
    item=states.get(key)
    if item is None:
        item=states.add(); item.name=key
    return item


def query_update(self,context):
    v=view(context)
    if v: v.pop('pin_contents',None); v['scroll']=0; v['offset_x']=0; v['browse_result']=False; v.pop('layout_key',None)


def tile_size_update(state,context):
    v=view(context)
    if v is None: return
    region=next((r for r in context.area.regions if r.type=='WINDOW'),None)
    if region:
        scale=context.preferences.system.ui_scale or 1.0
        _,old,_,_,columns=geometry(region.width,region.height,scale,v)
        first=int(v['scroll']//(old+CARD_FOOTER*scale))*columns
    v['tile_size']=state.tile_size
    if region:
        _,tile,_,_,columns=geometry(region.width,region.height,scale,v)
        v['scroll']=(first//columns)*(tile+CARD_FOOTER*scale)
    context.area.tag_redraw()


class SCB_PG_ui(bpy.types.PropertyGroup):
    tile_size:IntProperty(name='Thumbnail Size',description='Content tile width',default=DEFAULT_TILE_SIZE,min=76,max=256,update=tile_size_update)
    query:StringProperty(name='Search',update=query_update)


    scope:EnumProperty(items=[('ALL','全局','当前文件','WORLD',0),('HERE','当前','当前层级','FILE_FOLDER',1),('SUB','含下级','当前与所有下级','OUTLINER',2)],default='HERE',update=query_update)

    expanded:BoolProperty(name='展开所有层级',description='按深度优先顺序连续排列所有后代',update=query_update)


ICON_MASKS={'SCENE_DATA': [14, 14, 'c${Nk00YS-j~*?RVSsY(mdQvL-<4s>Ty$Xt)4Vb!1_s9Bg){#A{d=0}t~5l&<3E4?ykxyAeN3K#LE`?>?>~S3G@e(Gv!02eV4mfl|NsBD%K=T1D7-Jvxc~3}|9?~DmOpy5T%M7^A0+w5l?e!d1~FX)^8ULqLTye1O6~xPTOK}U!@$7x{Qn;Vpy;8$e~$vG+COtaS`PpHe*#E}Tmn1S=IAk70KG&}82'], 'OUTLINER_COLLECTION': [15, 14, 'c${O9Rzd)21_q`7aPU)!AomXt`~?CaSAl^+<tGsQ0E5pe5XCBbdU~n|y}CfI9yX&Clu&@e|NqF+__=b*Z~)XQ3jn3Wel-'], 'MESH_DATA': [14, 14, 'c${Nk0D@b8{@h_=fPp`(On;DgObiH~%%4Ah{>#I7)0<hC8fHNy)$a2%F!0^ifbdonG6KnhRbWZeJ6s@&{f-$(a7Q8|SV_W8prrE!R)_|c3m%NO{``eH<JR9lcM#41u|Up%fd4?&&F|muure_*GBV!!`SUIS;mS3w'], 'MATERIAL': [14, 14, 'c${NkVBjua_vq33N*)Ffu)X!??|(VpskiJI85nGS{s#gkMkc4bwv61j{)2f842-rnc}jl%`Sa)RUm%ZxaeCSE@1GYHI7{5w)Dgz&x#I3V9VSLb2B7qx3*mR~$}oZq{sYqd=fOHJ1n>X)vgu3+UKKakQV8!ZKZEUE2Sy0*j}s#Uqy4R^UJ^jwT_=ztM!xbj_aCgU<Ogy9y&+vw'], 'NODETREE': [14, 14, 'c$`g*VG2M%5JqPwat!(H1g_x>TDgh139`8q5&5azR%`4g`~JO}`5s?2u~rOTwk$xzbi)D3w8Nm9L>+76KoLZFW8d!kV00LD#Vn<~=F+b83@vU_fDak}i^3~H*m=b<Z^^!*Y7>Cn$w_@0;)^1d>g_-0X<JY'], 'IMAGE_DATA': [14, 14, 'c$~ZX2Lf(LfB*C6PVJxnU{J>d1b>9?f;o@)7=YkUSqxY*h7rtr!*b}?pTEbL7{I)5jHcgyezOEiF?{*M#JK415{MMTpFd0tGS}o85IhEuOz!;xMhFiC?*4tmgy7{pDnycFWMX7M@F1q#{0;*@fBw7+02{GX&H'], 'CURVE_DATA': [14, 14, 'c$~ZY|NlKE1{nCy%Jl#LwVkuVS;0Iepn#Tp+P1sNK>oe|{~t0jFfuZkZrRJqz{JGF2-d>Lv}7K_00st*y}?L4hS*uiJlQ+QJc$R$Jg*HP@-D<Zyx06-?qSl1z1zYBbI<=P+bkf~-TC$F9xEfr6#zQQD<='], 'ARMATURE_DATA': [14, 14, 'c${NkIM2?21dbUoLKx<=k1{Y!%K-D_P8|s4XJBx=B?RPX-AQEvi89u0(_>9~p2h@G&(!wv^S5p$m^n;LOg~wX4gL<2vN?>zvwm)m;90)32O66A{joQf_oKfbK%Afls!VzJ^I4cc);T@aXJokl{}IH3W0pXnya$C4w*mmBC?}l'], 'ACTION': [16, 14, 'c${Nk00FbZ7K{uCV0tt5rWqp=*MLdy214La6cYnO_+cg(-}tHugUVHe35*VB49+<r8ORv?C6tK)2`~yFTZaNn51Z*!*8)Mc4v@)c`sVLj3(MNNx;kq!Ak*yN-~ay)@qzd}V5ZK?|E~<JL3|rM5R*aguz^7pSigbZQ3FN*1pPL;'], 'LIGHT_DATA': [12, 15, 'c${Nk0D@b$m>3}7%&-6d|D1#Hn7{xczUSAUKY#XvIhIFRnV1-l*)uXQXxs;p4A%Fx8MrTnGx;(y_%elE;47QK#4r_v7-yC3a9~uNK6UC06$XbLulN~?RhXDm5*c}39yDVFX=Pw!Fg?^b31<DIX70<8U~z`X%X|zPXO=sNh&n7krvnsY&E5Lw(bhb61_l7uyDii'], 'CAMERA_DATA': [15, 15, 'c${NkU|_I(^#=%UF|l^v0`eGMIj}G>G5ygvz5Fi&!)~TOEFi%@e^#;lVPN?6=RXset9@=MP<9{d&!4}5;6D>b-+cxKMg}G(Mxb7x5+L?C`0EcCJlmGZ$l!6y6J#t9uvl)|%6iBdYz_!8GOaIo#m7+12;z9n_F*(WbJ&Ry%ww1pI*W<>jmIqyCXXBMH5q*8`ZF3FWAr%m{h(9mDxh7A46Dl+Kvps`&RcHEXu5hQJJeLx%#+`a7P2w`0DLV;Dg'], 'FILE_FONT': [12, 14, 'c${6#!3lsc429wNunPzd<sO3IfKtIp9K%CPLLdfh75z`&;qg{cZv%Ol)NH;;)T&9Kk{Y9$H9t;#;Iru>Zkxa6Vh-pxyg&GVqPmGRRu5^(B9cAk{RGZ&J?H'], 'COLOR': [14, 14, 'c${Nxe{jE<)vFc^@|yqr|NpmHzPt_$9{u<9_;a604#NHR-^1<Ce<lXGN)YeMpPxVf{AHS}FIU;n(D3Oe5PWCawq9SpxH{+Ce-L2Wvww>o6C)#>2jns^Ab21y5^w)3CMa(ckh2vor?&;jVTAD*bXEX44A*`E!5t<B1|XY(0RY2sb4~'], 'FONT_DATA': [13, 14, 'c${P4t2_1c=iUY>291Lkgs#uBX5|i8@;GEmE#IsbCPoGZMkcE#e|Z`1$}xZeqry)nhFh`>Q1FY1VR{`Sl=GR1LFncza~3cMsEk3N?$odUAn=C?q?HK_1l}<*z=6>PBu*E|q$BQN<1C&ifTZuXIB?jOKd@p1TV1{L%gu!bAT|KS6D;@'], 'EMPTY_DATA': [14, 14, 'c$_=t$jE>I*3TV~xQw>X?NGQcZBe*C{{q2(Ah-zPeqm*T0+8%aCM08N!n+3N0RZed7wi'], 'SURFACE_DATA': [14, 14, 'c${1K>kkB6W@2DqxNOP71OkH3K)jd6j0_+kc@@NaqzC3O$X^2S4!J?(7~gOM$;@M{5XnVVKw*{@XLP_kp$m(I7#Nts??SY4&A2ZK)ZuY~3Cv~cm<}SpKzIxqR~Z<t{`r3w!j*Z%!0?Tg=^KQnc@D^9V)zDi>v9H$Yu~@$XJuq$1i2Of%|<f#'], 'META_DATA': [14, 14, 'c${NkU`pNg=kJa*76uTIIJDJ=gWY@cVHqHYWq&;jBLf2?Q_Ue(28N`~5G4$ZTay?W_INTvcnmIknHU}jLOBc~cbFJn2|+p6?|+kG*x><H$z)P@O)hyW6I7Csv8I>la2?DT2K6&Q+jn?~?3V`d<nJ&ruqN$#_P-URpr#q5fr&}xeh;ry@qKxy7NyxQA1#t&1OV%~DlG'], 'LATTICE_DATA': [14, 14, 'c$_uOK?=e!5CzabgF#5qD+Pn`SXKhPl|kt-B%t70imOsE#2MPo;*mxE|If1CYX|hl4fD*2aA^r>mDn+SV$6h|(R?gmmFBw#l9OLoB?Sroq_1je?Fjy6nEhRF610N`mF=L52U<u0xt7d`x_FKl4UfyL>mkpww!V?4>0y|NSndzYk485'], 'VOLUME_DATA': [14, 14, 'c${PHcy+vjkpT)?_v;!S$%1j8=`k`Wym~l4Y|G0X4vhB{fI>_XmHQ(_y&gI?Y?lBjVPs@vVD#O>^l(2b%nXs+3`ewJ9EPCX472ND2KwLgWZ=8dYAD^ej)}qKwLMT=dd2^bD-{_Sv@SA%R4`rE0@1Sfz&wTyu-4Xz5T3%-Rt3?bhvHDv_!hnX(k%>R000~UEZz'], 'POINTCLOUD_DATA': [14, 14, 'c${Nkh`RlD3Ks(u*gy2q-rC0m<xMMQVo-So<IOH$WKehs<Z*}tc`ny&q*qU6VrcvSai2H?W5(mpb9foTPN)b>na#k!$ixIxH$Rz?LE;t6=xKF~42Jjkmi~X2&&a@F{4mY)MBVJA5>_|d7#SGd_Ma_gc`eJpSTKVLteuhJwF(16#Uz;JeOvWH9@{WNc^v%@FNeUS7yuxTE>H'], 'CURVES_DATA': [14, 14, 'c$|C2!NBmEje+3>kY-@`C&s|=OOAozo&_V2_f?sJ;f^gM!|YkiK;8>|28P*fj0~bbJb{w8fhrvC0L5K@&$nPa7RboJ{Mw$8fl+Mw?Ps+sfZ~x4S%8|DnVFS;0~w6xszD}#jIjbTlz+uRxOIm>MjQY21#{V627zeXd(2=-uTLOHF+w;DjC)$4Mu36BZDtq~08q0gG5'], 'GREASEPENCIL': [14, 14, 'c$_=8yUvM~0S0#e`TOU+6C;#Y`{)1v|6d%STw4(D|7R$d<K>?}fBydcWDnt5zWVv|`}gl}Y`|Pb>kt3IifvK3f?&0bHel{1sI`nXpZ@>f!ngc`8I=2Z6W`K5|2IKp<+&FDEj|WwAvaL(HygNvjW(XJWds04!b^J'], 'SPEAKER': [14, 14, 'c${OX7iT~Kso6|SeOxeJY$T&k86%80MV6sYjiL1PsUncjL~(}Md<+-={{7nq<aWq0OqF1$|NismT_y&GW<7?4Fh<6V(`Ww!d2SVq67zK#7@3&<0C_C4<rvl4fD8r@kHNEBfDuGPc#J`_6&T<=21esHgdC6yq5k~&a}VL-+kgMw1^@{7DJT'], 'LIGHTPROBE_SPHERE': [13, 13, 'c$~ZQ7Ye@EGcx>TWrBc1FYOrrGBH5F2D_Iwzu+7uySLwgoczbdj0|g-7{7s(-K~4T1e9U;3*w~R%3*|a7?~Iu;2fv{41Yf!-T(ocbr}BIytIc{s<lApFQd&%8%D4?twsMCfV`g|@axx~=KvzTKC='], 'OBJECT_DATA': [14, 14, 'c$}4vOA3H63`E16+~N&Faycn@3#HH!n+}3o-zqO3GMl?Y5_8`jpvWxV0ZBXhqC#@i`j|vOa_?&Qf;T<LFEdD`oS1QtAr}1p$x>964K*tdTYOIP'], 'FILE': [12, 14, 'c$~ZS2M+H1VP%4WKYy4QU;u^v6N&u|!Ty4*2Ek<ba~^CmSmcl8hyOqTVKZ8PfU_AGZ9c%+K+Y#P8_0S2{rmTyKkotn1UNW<'], 'WORLD': [14, 14, 'c$^)MK?;IE7={0Ta1n-Wg`|^6140WCicX_q=p6#dBeW3Q*bV9qQ8+OX)UJ(-fnj8F`gY%YZ}HAcw3E||H^~$L{CC2t&0@YT?-T)Jz9QJmoCJ*Gqze#0Xq6Lsb>ag7NaZjnf>qo^WAzn6>=44^(}P|X79nHkGUkCO#<9WW^)^#V=4dQz<D1f24}UE)yVC|^OXdKTS{Ig)M>?LNOc&@zdzO5B0Cdut@iv>GfB6AtFi;B'], 'TEXTURE': [14, 14, 'c$|HXK?=Yi3<M=m`u~3j{-F|CsLv?`C1O)Vs68}?fn}E=9<K}7h-zztC&)SNeK4;nNhvmysyh*)B`Yow<AFA3Mm$bY9n61D)HyTaV_A|<05jXmi8<WylW&g'], 'PARTICLES': [14, 14, 'c$_tiK?=e!5Ji9H98$Lp@gzb~D4xV4C|K&&g(ykEZNZQMdnh+9MX<!AiGMM}oA((kua!Vd*|ZXx4NY`#++gkM<W9^jgiT7_&PN5@Cnb%dc<$pUFDmt8Q<_Br><O~_1H#_s8fNyx1!V#L`f*59>+0#ff6>l{IM$ER`+)?7Y`Rrp-)^4Yk@x}8+b=W'], 'MODIFIER': [14, 14, 'c%0MRc+`TC0R}ey`TN-c&OP|||NqbSFs|u`|3I!Sl*?%S_RpWcpO!v)wA&ge#Ax&8=lAd5fapsxnEUxZ1pIOWDPH;)sFTI^)BjZ<y^sI@0h-Ea^XV0ccjy047LXd76CmFDzkk6tGBSbf{DrU)D3<jdg=@L!)k%;t07o-NPy'], 'ANIM_DATA': [14, 14, 'c${NkfPsUyj0^~1^BkGWX!G0#NU_g&`UedD-v#ofP7-HgVq{{ne`ycoofikIw0r>8w>}oE`=|q$(tHLMWMYJwZG&pICX&UB3G11VxDuC<ctU-%A-ogczJLGzcrG_Y7y$LbA#M']}


EXTRA_OBJECT_ICONS={'FONT':'FONT_DATA','EMPTY':'EMPTY_DATA','SURFACE':'SURFACE_DATA','META':'META_DATA',
                    'LATTICE':'LATTICE_DATA','VOLUME':'VOLUME_DATA','POINTCLOUD':'POINTCLOUD_DATA',
                    'GREASEPENCIL':'GREASEPENCIL','SPEAKER':'SPEAKER','LIGHT_PROBE':'LIGHTPROBE_SPHERE'}


EXTRA_ID_ICONS={'WORLD':'WORLD','TEXTURE':'TEXTURE','KEY':'ANIM_DATA','PARTICLE':'PARTICLES',
                'VOLUME':'VOLUME_DATA','LATTICE':'LATTICE_DATA','META':'META_DATA','POINTCLOUD':'POINTCLOUD_DATA',
                'GREASEPENCIL':'GREASEPENCIL','SPEAKER':'SPEAKER','LIGHT_PROBE':'LIGHTPROBE_SPHERE'}


ID_GROUPS={'SCENE':'Scene','COLLECTION':'Collection','MESH':'Mesh','MATERIAL':'Material','IMAGE':'Image','CURVE':'Curve',
           'CURVES':'Curve','ARMATURE':'Armature','ACTION':'Action','LIGHT':'Light','CAMERA':'Camera','FONT':'Fonts','PALETTE':'Palette'}


@lru_cache(maxsize=128)
def type_icons(id_type,subtype):
    if id_type=='NODETREE':
        icons=(FILTER_ICONS['NodeGroup'],)
        if subtype=='ShaderNodeTree': return icons+(FILTER_ICONS['Material'],)
        if subtype=='GeometryNodeTree': return icons+(FILTER_ICONS['Mesh'],)
        return icons
    if id_type=='OBJECT':
        group=OBJECT_GROUPS.get(subtype)
        return (FILTER_ICONS[group] if group else EXTRA_OBJECT_ICONS.get(subtype,'OBJECT_DATA'),)
    group=ID_GROUPS.get(id_type)
    return (FILTER_ICONS[group] if group else EXTRA_ID_ICONS.get(id_type,'FILE'),)


def icon_batch(icon):
    import base64,zlib
    if icon not in R.type_batches:
        w,h,payload=ICON_MASKS[icon]
        mask=zlib.decompress(base64.b85decode(payload))
        vertices=[]
        colors=[]
        for i,coverage in enumerate(mask):
            if not coverage: continue
            x=(16-w)/2+i%w
            y=(16-h)/2+i//w
            vertices.extend(((x,y),(x+1,y),(x+1,y+1),(x,y),(x+1,y+1),(x,y+1)))
            colors.extend([(*META_COLOR[:3],coverage/255)]*6)
        shader=gpu.shader.from_builtin('SMOOTH_COLOR')
        batch=batch_for_shader(shader,'TRIS',{'pos':vertices,'color':colors})
        R.type_batches[icon]=(shader,batch)
    return R.type_batches[icon]


def draw_type_icons(item,x,y,scale):
    subtype=item.type if isinstance(item,bpy.types.Object) else item.bl_idname if isinstance(item,bpy.types.NodeTree) else ''
    blend=gpu.state.blend_get()
    try:
        gpu.state.blend_set('ALPHA')
        for icon in type_icons(item.id_type,subtype):
            shader,batch=icon_batch(icon)
            with gpu.matrix.push_pop():
                gpu.matrix.translate((x,y,0))
                gpu.matrix.scale((scale,scale,1))
                shader.bind()
                batch.draw(shader)
            x+=17*scale
    finally:
        gpu.state.blend_set(blend)


def library_filter_update(name):
    def update(state,context):
        if not state.filter_Palette and not state.filter_Fonts or (
                getattr(state,'filter_'+name) and not getattr(state,'filter_'+('Palette' if name=='Fonts' else 'Fonts'))):
            for group in GROUPS:
                if group not in {'Palette','Fonts'} and getattr(state,'filter_'+group):
                    setattr(state,'filter_'+group,False)
        query_update(state,context)
    return update


for group in GROUPS:
    update=library_filter_update(group) if group in {'Fonts','Palette'} else query_update
    SCB_PG_ui.__annotations__['filter_'+group]=BoolProperty(name=group,default=False,update=update)


class SCB_MT_context(bpy.types.Menu):
    bl_label='QuickBrowser'
    bl_idname='SCB_MT_context'
    def draw(self,context):
        layout=self.layout
        v=view(context)
        item=resolve(v['selected']) if v else None
        if item is None: return
        actions=[('REFRESH','Refresh Preview')]
        if isinstance(item,(bpy.types.Object,bpy.types.Material)):
            actions.append(('FRAME','Frame Selected | Shift+C'))
        if isinstance(item,(bpy.types.Object,bpy.types.Material,bpy.types.Image)):
            actions.append(('UNLINK','Remove from Scene | X'))
        actions.append(('DELETE','Delete Data-Block | Shift+X'))
        for action,label in actions:
            op=layout.operator('scb.item_action',text=label,translate=False)
            op.action=action
            op.target=str(item.session_uid)


class SCB_PT_directories(bpy.types.Panel):
    bl_label='Folders'
    bl_space_type='PROPERTIES'
    bl_region_type='WINDOW'
    bl_context='scene'
    bl_options={'HIDE_HEADER'}
    @classmethod
    def poll(cls,context): return bool(view(context))
    def draw(self,context):
        v=view(context)
        scale=context.preferences.system.ui_scale
        sidebar=geometry(context.region.width,context.region.height,scale,v)[0]
        if not sidebar: return
        # Actual native layout; GPU never paints over this column.
        layout=self.layout
        split=layout.split(factor=min(.9,sidebar/max(1,context.region.width)),align=True)
        col=split.column(align=True)
        col.scale_y=1.3
        for name,path,uid,depth in tree_rows(v):
            row=col.row(align=True)
            if depth:
                spacer=row.row(); spacer.ui_units_x=depth*.45; spacer.label(text='')
            op=row.operator('scb.native',text=name,icon='FILE_FOLDER' if uid else 'HOME',
                            depress=path==v['path'])
            op.action='PATH'; op.path='/'.join(str(x) for x in path)
        split.column().separator()


def header_draw(self,context):
    if not view(context):
        R.header_original(self,context)
        return
    layout=self.layout
    layout.template_header()
    layout.menu('SCB_MT_context',text='Browser')
    row=layout.row(align=True)
    row.operator('scb.native',text='',icon='HOME').action='ROOT'
    row.operator('scb.native',text='',icon='FILE_PARENT').action='UP'
    v=view(context)
    row.operator('scb.native',text='',icon='MENU_PANEL').action='SIDE'
    row.scale_x=.85
    for i,uid in enumerate(v['path']):
        item=resolve(uid)
        if item:
            if i: row.label(text='/')
            op=row.operator('scb.native',text=item.name,emboss=False)
            op.action='PATH'; op.path='/'.join(str(x) for x in v['path'][:i+1])
    layout.separator_spacer()
    state=ui_state(context)
    buttons=layout.row(align=True)
    for group,icon in FILTER_ICONS.items():
        buttons.prop(state,'filter_'+group,text='',icon=icon,toggle=True)
    buttons.separator(type='LINE')
    buttons.operator('scb.native',text='',icon='FILE_REFRESH').action='REFRESH'
    buttons.prop(state,'expanded',text='',icon='OUTLINER',toggle=True)
    buttons.operator('scb.native',text='',icon='PINNED' if v.get('pin') else 'UNPINNED',depress=bool(v.get('pin'))).action='PIN'
    layout.separator_spacer()
    layout.prop(state,'query',text='',icon='VIEWZOOM')
    layout.row(align=True).prop(state,'scope',expand=True,icon_only=True)
    slider=layout.row(align=True)
    slider.ui_units_x=4
    slider.prop(state,'tile_size',text='',slider=True)


class SCB_BrowserTree(bpy.types.NodeTree):
    bl_idname=TREE
    bl_label='QuickBrowser'
    bl_icon='FILE_FOLDER'


def restore_nav(window,area,v):
    if v.get('nav_hidden') and area.type=='PROPERTIES':
        region=next((r for r in area.regions if r.type=='NAVIGATION_BAR'),None)
        if region and region.width<=4:
            with bpy.context.temp_override(window=window,area=area):
                bpy.ops.screen.region_toggle(region_type='NAVIGATION_BAR')

class QuickBrowserPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    def draw(self, context):
        col = self.layout.column(align=True)
        col.label(text="QuickBrowser 使用说明")
        col.label(text="在区域左上角的编辑器类型菜单选择 QuickBrowser。")
        col.label(text="双击进入下一级，Tab 返回。拖动空白处框选，F2 重命名。")
        col.label(text="对象下按 X 移除选中的材质插槽；Shift+X 从文件中删除数据块。")
        col.label(text="将对象拖到 3D 视图创建副本。完整说明见安装目录的 README.md。")
