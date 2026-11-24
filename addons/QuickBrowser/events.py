# SPDX-License-Identifier: GPL-3.0-or-later
from .browser_data import R
from .browser_data import akey
from .browser_data import current
from .browser_data import navigate
from .browser_data import resolve
from .browser_data import results
from .operators import can_replace
from .operators import defer_item_edit
from .operators import drop_selection
from .operators import open_item
from .operators import return_to_browser
from .operators import show_shader
from .previews import raster_thumbnail
from .previews import refresh_previews
from .ui import CARD_FOOTER
from .ui import geometry
from .ui import restore_nav
from .ui import thumbnail
from .ui import ui_state
from bpy_extras import view3d_utils
import bpy
import gpu
import math
import sys
import time


class DragOverlay:
    """Click-through Windows drag image, owned only for the duration of the drag."""
    def __init__(self,pixels):
        import ctypes as C
        from ctypes import wintypes as W
        import numpy as np
        self.user=C.WinDLL('user32',use_last_error=True)
        gdi=C.WinDLL('gdi32',use_last_error=True)
        handle=C.c_void_p
        def bind(lib,name,result,*args):
            fn=getattr(lib,name); fn.restype=result; fn.argtypes=args
            return fn
        create=bind(self.user,'CreateWindowExW',handle,W.DWORD,W.LPCWSTR,W.LPCWSTR,W.DWORD,C.c_int,C.c_int,C.c_int,C.c_int,handle,handle,handle,handle)
        self.destroy=bind(self.user,'DestroyWindow',W.BOOL,handle)
        self.position=bind(self.user,'SetWindowPos',W.BOOL,handle,handle,C.c_int,C.c_int,C.c_int,C.c_int,W.UINT)
        self.cursor=bind(self.user,'GetCursorPos',W.BOOL,C.POINTER(W.POINT))
        self.point=W.POINT()
        rgba=np.clip(pixels,0,1)
        ys,xs=np.where(rgba[:,:,3]>.02)
        if len(xs):
            rgba=rgba[ys.min():ys.max()+1,xs.min():xs.max()+1]
        bgra=rgba[::-1,:,[2,1,0,3]].copy()
        bgra[:,:,:3]=np.minimum(bgra[:,:,:3],bgra[:,:,3:])
        bits=np.ascontiguousarray(np.rint(bgra*255),dtype=np.uint8)
        height,width=bits.shape[:2]
        class Bitmap(C.Structure):
            _fields_=[('size',W.DWORD),('width',W.LONG),('height',W.LONG),('planes',W.WORD),('depth',W.WORD),
                      ('compression',W.DWORD),('bytes',W.DWORD),('x',W.LONG),('y',W.LONG),('used',W.DWORD),('important',W.DWORD)]
        class Blend(C.Structure):
            _fields_=[('op',C.c_ubyte),('flags',C.c_ubyte),('alpha',C.c_ubyte),('format',C.c_ubyte)]
        dc=bind(gdi,'CreateCompatibleDC',handle,handle)(None)
        dib=old=None
        self.hwnd=None
        try:
            addr=handle()
            header=Bitmap(C.sizeof(Bitmap),width,-height,1,32)
            dib=bind(gdi,'CreateDIBSection',handle,handle,C.POINTER(Bitmap),W.UINT,C.POINTER(handle),handle,W.DWORD)(dc,C.byref(header),0,C.byref(addr),None,0)
            if not dib or not addr: raise C.WinError()
            C.memmove(addr,bits.ctypes.data,bits.nbytes)
            select=bind(gdi,'SelectObject',handle,handle,handle)
            old=select(dc,dib)
            # Layered + transparent + tool window + no activation.
            self.hwnd=create(0x080800A0,'STATIC',None,0x80000000,0,0,width,height,None,None,None,None)
            if not self.hwnd: raise C.WinError()
            update=bind(self.user,'UpdateLayeredWindow',W.BOOL,handle,handle,C.POINTER(W.POINT),C.POINTER(W.SIZE),handle,C.POINTER(W.POINT),W.DWORD,C.POINTER(Blend),W.DWORD)
            self.cursor(C.byref(self.point))
            dest=W.POINT(self.point.x+3,self.point.y+3)
            if not update(self.hwnd,None,C.byref(dest),C.byref(W.SIZE(width,height)),dc,C.byref(W.POINT()),0,C.byref(Blend(0,0,255,1)),2):
                raise C.WinError()
            self.move()
        except Exception:
            self.close()
            raise
        finally:
            if old: select(dc,old)
            if dib: bind(gdi,'DeleteObject',W.BOOL,handle)(dib)
            if dc: bind(gdi,'DeleteDC',W.BOOL,handle)(dc)

    def move(self):
        import ctypes as C
        if self.hwnd and self.cursor(C.byref(self.point)):
            self.position(self.hwnd,-1,self.point.x+3,self.point.y+3,0,0,0x0051)

    def close(self):
        if self.hwnd:
            self.destroy(self.hwnd)
            self.hwnd=None


def clear_drag(owner=None):
    window_id=getattr(R,'drag_window',None)
    if owner is not None and owner!=window_id: return
    overlay=getattr(R,'drag_overlay',None)
    if overlay: overlay.close()
    R.drag_overlay=None
    R.overlay_failed=False
    visible=R.drag is not None
    R.drag=None
    R.drag_window=None
    if visible:
        window=next((w for w in bpy.context.window_manager.windows if w.as_pointer()==window_id),None)
        if window:
            for area in window.screen.areas: area.tag_redraw()


def drag_preview():
    if not R.drag: return
    uid,mx,my=R.drag
    if bpy.context.window.as_pointer()!=getattr(R,'drag_window',0): return
    if sys.platform=='win32' and not getattr(R,'overlay_failed',False):
        if not getattr(R,'drag_overlay',None):
            item=resolve(uid)
            if item:
                import numpy as np
                try:
                    tex=raster_thumbnail((56,56),lambda w,h:thumbnail(item,0,0,w,getattr(R,'drag_path',())))
                    R.drag_overlay=DragOverlay(np.asarray(tex.read()).reshape(56,56,4))
                except (OSError,RuntimeError,ValueError) as exc:
                    R.overlay_failed=True
                    print('QuickBrowser drag image:',exc)
        if getattr(R,'drag_overlay',None): return
    region=bpy.context.region
    x=mx-region.x; y=my-region.y
    if 0<=x<region.width and 0<=y<region.height:
        item=resolve(uid)
        if item:
            gpu.state.blend_set('ALPHA')
            try: thumbnail(item,max(0,min(x+3,region.width-56)),max(0,min(y+3,region.height-56)),56)
            finally: gpu.state.blend_set('NONE')


def hit_test(v,x,y):
    if v.get('clip') and not v['clip'][0]<=y<v['clip'][1]: return None,None
    for (a,b,w,h),kind,payload in reversed(v['hits']):
        if a<=x<a+w and b<=y<b+h: return kind,payload
    return None,None


class SCB_OT_events(bpy.types.Operator):
    bl_idname='scb.events'
    bl_label='QuickBrowser Events'
    def invoke(self,context,event):
        self.window_id=context.window.as_pointer()
        if self.window_id in R.running: return {'CANCELLED'}
        R.running.add(self.window_id)
        self.press=None
        self.dragging=False
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}
    def cancel(self,context):
        self.press=None
        self.dragging=False
        clear_drag(self.window_id)
        R.running.discard(self.window_id)

    def modal(self,context,event):
        if not R.alive:
            self.cancel(context)
            return {'CANCELLED'}
        window=context.window
        if not window or window.as_pointer()!=self.window_id: return {'PASS_THROUGH'}
        if event.type=='Z' and (event.ctrl or event.oskey):
            self.press=None
            self.dragging=False
            clear_drag(self.window_id)
            return {'PASS_THROUGH'}
        if event.type=='WINDOW_DEACTIVATE':
            self.press=None; self.dragging=False
            clear_drag(self.window_id)
            return {'PASS_THROUGH'}
        area=next((a for a in window.screen.areas if a.x<=event.mouse_x<a.x+a.width and a.y<=event.mouse_y<a.y+a.height),None)
        region=next((r for r in area.regions if r.type=='WINDOW' and r.x<=event.mouse_x<r.x+r.width and r.y<=event.mouse_y<r.y+r.height),None) if area else None
        v=R.views.get(akey(window,area)) if area else None
        if area and area.type!='PROPERTIES':
            if region and event.type=='TAB' and event.value=='PRESS' and not (event.ctrl or event.shift or event.alt) and return_to_browser(window,area):
                return {'RUNNING_MODAL'}
            v=None
        if self.press and (self.press['key'] not in R.views or resolve(self.press['uid']) is None
                           or (self.dragging and not R.drag)):
            self.press=None
            self.dragging=False
            clear_drag(self.window_id)
            return {'PASS_THROUGH'}
        if getattr(self,'pending_edit',None):
            if event.type=='LEFTMOUSE' and event.value=='RELEASE':
                key,uid=self.pending_edit; self.pending_edit=None
                if key in R.views and (item:=resolve(uid)):
                    if isinstance(item,bpy.types.Image): open_item(context,R.views[key],uid)
                    else: show_shader(context,R.views[key],item,True)
            elif event.type=='ESC': self.pending_edit=None
            return {'RUNNING_MODAL'}
        if getattr(self,'box_key',None):
            bv=R.views.get(self.box_key)
            if not bv or not bv.get('box'):
                self.box_key=None
                return {'PASS_THROUGH'}
            ax,ay,_,_=bv['box']
            rx,ry,*_=bv['region']
            bx,by=event.mouse_x-rx,event.mouse_y-ry
            bv['box']=(ax,ay,bx,by)
            if area and (event.type!='MOUSEMOVE' or time.monotonic()-bv.get('box_frame',0)>=1/60):
                area.tag_redraw(); bv['box_frame']=time.monotonic()
            if event.type=='ESC' or (event.type=='LEFTMOUSE' and event.value=='RELEASE'):
                if event.type!='ESC':
                    selected=set(self.base_selection)
                    refs=set(self.base_slots)
                    for (x,y,w,h),kind,uid in bv['hits']:
                        if kind=='tile' and x<=max(ax,bx) and x+w>=min(ax,bx) and y<=max(ay,by) and y+h>=min(ay,by):
                            selected.add(uid)
                            ref=bv.get('slot_hits',{}).get((x,y,w,h))
                            if ref: refs.add(ref)
                    bv['slot_selection']=refs
                    bv['multi']=selected; bv['selected']=next(iter(selected),0)
                bv.pop('box',None); self.box_key=None
            return {'RUNNING_MODAL'}
        finishing=event.type=='LEFTMOUSE' and event.value=='RELEASE'
        if event.type in {'ESC','RIGHTMOUSE'} and self.press:
            self.press=None; self.dragging=False; clear_drag(self.window_id)
            return {'RUNNING_MODAL'}
        if event.type=='MOUSEMOVE' and self.press:
            if math.hypot(event.mouse_x-self.press['x'],event.mouse_y-self.press['y'])>7:
                if isinstance(resolve(self.press['uid']),(bpy.types.Scene,bpy.types.Action)):
                    self.press=None
                    return {'RUNNING_MODAL'}
                if not self.dragging:
                    source_view=R.views.get(self.press['key'],{})
                    R.drag_path=tuple(source_view.get('path',()))+tuple(source_view.get('clicked_path',())[:-1])
                self.dragging=True
                R.drag_window=self.window_id
                R.drag=(self.press['uid'],event.mouse_x,event.mouse_y)
            overlay=getattr(R,'drag_overlay',None)
            if overlay: overlay.move()
            else:
                for editor in window.screen.areas: editor.tag_redraw()
            return {'RUNNING_MODAL'}
        if finishing and self.press:
            press=self.press; self.press=None; clear_drag(self.window_id)
            if self.dragging:
                self.dragging=False
                drop_x,drop_y=event.mouse_x,event.mouse_y
                if region and v:
                    kind,payload=hit_test(v,drop_x-region.x,drop_y-region.y)
                    uid=payload if kind=='tile' else payload[0] if kind=='tree' else 0
                    target=resolve(uid)
                    if event.alt:
                        if len(press['group'])==1 and can_replace(resolve(press['uid']),target):
                            defer_item_edit(window,area,'REMAP',uid,press['uid'])
                    elif isinstance(resolve(press['uid']),bpy.types.NodeTree):
                        if isinstance(target,bpy.types.Object):
                            with context.temp_override(window=window,area=area,region=region):
                                drop_selection(context,press,target=str(uid))
                    elif isinstance(target,(bpy.types.Scene,bpy.types.Collection)):
                        with context.temp_override(window=window,area=area,region=region):
                            drop_selection(context,press,target=str(uid),keep=event.shift)
                    else: R.message='Drop onto a Collection / Scene folder in this browser'
                elif region and area.type=='NODE_EDITOR' and isinstance(resolve(press['uid']),bpy.types.NodeTree):
                    nx,ny=region.view2d.region_to_view(drop_x-region.x,drop_y-region.y)
                    scale=context.preferences.system.ui_scale
                    with context.temp_override(window=window,area=area,region=region):
                        drop_selection(context,press,location=(nx/scale,ny/scale,0))
                elif region and area.type=='VIEW_3D':
                    rv3d=area.spaces.active.region_3d
                    if rv3d:
                        point=view3d_utils.region_2d_to_location_3d(region,rv3d,
                              (drop_x-region.x,drop_y-region.y),window.scene.cursor.location)
                        with context.temp_override(window=window,area=area,region=region):
                            coord=(drop_x-region.x,drop_y-region.y)
                            origin=view3d_utils.region_2d_to_origin_3d(region,rv3d,coord)
                            direction=view3d_utils.region_2d_to_vector_3d(region,rv3d,coord)
                            found,loc,normal,face,hit,matrix=context.scene.ray_cast(context.evaluated_depsgraph_get(),origin,direction)
                            drop_selection(context,press,location=point,
                                             hover=str(hit.original.session_uid) if found else '')
                else: R.message='Supported drop targets: 3D View or browser collection'
            else:
                source_view=R.views.get(press['key'])
                if source_view:
                    source_view['multi']={press['uid']}
                    now=time.monotonic()
                    if source_view['last'][0]==(press.get('slot') or press['uid']) and now-source_view['last'][1]<.45:
                        open_item(context,source_view,press['uid'])
                        source_view['last']=(0,0)
                    else:
                        source_view['last']=(press.get('slot') or press['uid'],now)
            return {'RUNNING_MODAL'}
        if not v or not region: return {'PASS_THROUGH'}
        x,y=event.mouse_x-region.x,event.mouse_y-region.y
        sidebar=geometry(region.width,region.height,context.preferences.system.ui_scale,v)[0]
        if getattr(self,'resizing',False):
            if event.type=='MOUSEMOVE':
                scale=context.preferences.system.ui_scale
                v['width']=max(45,min(region.width*.65,x))/scale
                v['hidden']=x<25*scale
                area.tag_redraw()
            if event.type=='LEFTMOUSE' and event.value=='RELEASE': self.resizing=False
            return {'RUNNING_MODAL'}
        if event.type=='LEFTMOUSE' and event.value=='PRESS' and sidebar>0 and abs(x-sidebar)<6:
            self.resizing=True
            return {'RUNNING_MODAL'}
        if event.type=='MOUSEMOVE':
            if sidebar>0 and abs(x-sidebar)<6:
                window.cursor_set('MOVE_X')
                self.edge_cursor=True
            elif getattr(self,'edge_cursor',False):
                window.cursor_set('DEFAULT')
                self.edge_cursor=False
        if event.type=='TAB' and event.value=='PRESS' and not (event.ctrl or event.alt or event.shift):
            if v['path']:
                child=v['path'][-1]
                navigate(v,0,v['path'][:-1])
                v['selected']=child
                v['multi']={child}
                with context.temp_override(window=window,area=area,region=region):
                    state=ui_state(context)
                    listing=results(current(v),state)
                    index=next((i for i,item in enumerate(listing) if item.session_uid==child),None)
                    if index is not None:
                        scale=context.preferences.system.ui_scale
                        _,tile,_,_,cols=geometry(region.width,region.height,scale,v)
                        v['scroll']=(index//cols)*(tile+CARD_FOOTER*scale)
                area.tag_redraw()
            return {'RUNNING_MODAL'}
        if event.type=='F2' and event.value=='PRESS' and v['selected']:
            with context.temp_override(window=window,area=area,region=region):
                bpy.ops.scb.rename('INVOKE_DEFAULT',batch=event.ctrl)
            return {'RUNNING_MODAL'}
        if event.value=='PRESS' and v['selected'] and (event.type=='X' or event.type=='C' and event.shift):
            with context.temp_override(window=window,area=area,region=region):
                if event.type=='C': bpy.ops.scb.item_action(action='FRAME')
                else: defer_item_edit(window,area,'DELETE' if event.shift else 'UNLINK',v['selected'])
            return {'RUNNING_MODAL'}
        if x<sidebar: return {'PASS_THROUGH'}
        def hovered_slot():
            return next((ref for (ax,ay,w,h),ref in v.get('slot_hits',{}).items() if ax<=x<ax+w and ay<=y<ay+h),None)
        if event.type=='RIGHTMOUSE' and event.value=='PRESS':
            kind,payload=hit_test(v,x,y)
            if kind not in {'tile','shield'}: return {'RUNNING_MODAL'}
            ref=hovered_slot()
            if ref and ref not in v.get('slot_selection',()):
                v['slot_selection']={ref}
                v['multi']={payload}
            if payload not in v.get('multi',()):
                v['multi']={payload}
                v['slot_selection']={ref} if ref else set()
            area.tag_redraw()
            v['selected']=payload
            with context.temp_override(window=window,area=area,region=region):
                bpy.ops.wm.call_menu(name='SCB_MT_context')
            return {'RUNNING_MODAL'}
        if event.type in {'WHEELUPMOUSE','WHEELDOWNMOUSE'} and event.shift and v.get('max_x',0):
            v['offset_x']=max(0,min(v['max_x'],v.get('offset_x',0)+(90 if event.type=='WHEELDOWNMOUSE' else -90)))
            area.tag_redraw()
            return {'RUNNING_MODAL'}
        if event.type in {'WHEELUPMOUSE','WHEELDOWNMOUSE'}:
            sidebar=geometry(region.width,region.height,context.preferences.system.ui_scale,v)[0]
            field='tree_scroll' if x<sidebar else 'scroll'
            maximum=v['max_tree'] if x<sidebar else v['max_scroll']
            v[field]=max(0,min(maximum,v[field]+(-48 if event.type=='WHEELUPMOUSE' else 48)))
            area.tag_redraw()
            return {'RUNNING_MODAL'}
        if event.type=='LEFTMOUSE' and event.value in {'PRESS','DOUBLE_CLICK'}:
            kind,payload=hit_test(v,x,y)
            R.message=''
            if kind=='shield':
                with context.temp_override(window=window,area=area,region=region):
                    defer_item_edit(window,area,'FAKE_USER',payload)
                return {'RUNNING_MODAL'}
            if kind=='edit':
                mat=resolve(payload)
                v['clicked_path']=next((path for ax,ay,ww,hh,path in v.get('tile_paths',()) if ax<=x<ax+ww and ay<=y<ay+hh),())
                if mat: self.pending_edit=(akey(window,area),payload)
                return {'RUNNING_MODAL'}
            if kind is None:
                self.box_key=akey(window,area)
                self.base_slots=set(v.get('slot_selection',())) if event.shift or event.ctrl else set()
                self.base_selection=set(v.get('multi',())) if event.shift or event.ctrl else set()
                v['box']=(x,y,x,y)
                return {'RUNNING_MODAL'}
            if kind=='tile':
                v['clicked_path']=next((path for ax,ay,ww,hh,path in v.get('tile_paths',()) if ax<=x<ax+ww and ay<=y<ay+hh),())
                ref=hovered_slot()
                refs=v.setdefault('slot_selection',set())
                if event.ctrl or event.shift:
                    if ref:
                        if event.ctrl and ref in refs: refs.remove(ref)
                        else: refs.add(ref)
                        multi=v.setdefault('multi',set())
                        if any(r[2]==payload for r in refs): multi.add(payload)
                        else: multi.discard(payload)
                        v['selected']=payload if payload in multi else next(iter(multi),0)
                        area.tag_redraw()
                        return {'RUNNING_MODAL'}
                else:
                    v['slot_selection']={ref} if ref else set()
                multi=v.setdefault('multi',set())
                if event.shift or event.ctrl:
                    if payload in multi and event.ctrl: multi.remove(payload)
                    else: multi.add(payload)
                    v['selected']=payload if payload in multi else next(iter(multi),0)
                    return {'RUNNING_MODAL'}
                if payload not in multi: v['multi']={payload}
                v['selected']=payload

                parent=current(v)
                self.press=dict(uid=payload,slot=ref,group=[(uid,(path[-2] if len(path)>1 else (parent.session_uid if parent else 0))) for _,_,uid,path in v.get('positions',[]) if uid in v['multi'] and not isinstance(resolve(uid),(bpy.types.Scene,bpy.types.Action))],source=parent.session_uid if isinstance(parent,(bpy.types.Scene,bpy.types.Collection)) else 0,
                                key=akey(window,area),x=event.mouse_x,y=event.mouse_y)
            elif kind=='tree': navigate(v,0,payload[1])
            elif kind=='root': navigate(v,0,[])
            elif kind=='up': navigate(v,0,v['path'][:-1])
            elif kind=='search':
                with context.temp_override(window=window,area=area,region=region): bpy.ops.scb.search('INVOKE_DEFAULT')
            elif kind=='refresh':
                refresh_previews()
            elif kind=='exit':
                restore_nav(window,area,v)
                R.views.pop(akey(window,area),None)
            area.tag_redraw()
            return {'RUNNING_MODAL'}
        return {'PASS_THROUGH'}
