import * as THREE from 'three';

// OrbitControls internally bounds its spherical input away from exact poles.
// Only that hidden input uses EPS; the rendered camera stays exactly square.
const POLE_EPS=1e-6;

/** Model-relative Z-up turntable. Input and output share WORLD coordinates.
 * Heading survives exact poles; an analytic basis avoids lookAt singularities.
 * Never rotate the input frame to manufacture matching screen-relative deltas. */
export class CameraRig {
  input: THREE.OrthographicCamera;
  target = new THREE.Vector3();
  distance=15000;
  heading=0;
  inclination=Math.PI/2;
  constructor(public output: THREE.OrthographicCamera) {
    this.input=output.clone();this.input.up.set(0,0,1);
  }
  // Compatibility for existing world-space pan/focus callers. No rotated frame.
  world(point: THREE.Vector3){return point.clone();}
  local(point: THREE.Vector3){return point.clone();}
  snap(target:THREE.Vector3,direction:THREE.Vector3,up:THREE.Vector3,distance:number){
    this.target.copy(target);this.distance=distance;
    const normal=direction.clone().normalize();
    this.inclination=Math.atan2(Math.hypot(normal.x,normal.y),normal.z);
    this.heading=Math.hypot(normal.x,normal.y)>1e-10
      ?Math.atan2(normal.x,-normal.y)
      :normal.z>0?Math.atan2(-up.x,up.y):Math.atan2(up.x,-up.y);
    const phi=THREE.MathUtils.clamp(this.inclination,POLE_EPS,Math.PI-POLE_EPS);
    this.input.up.set(0,0,1);
    this.input.position.copy(target).addScaledVector(new THREE.Vector3(Math.sin(phi)*Math.sin(this.heading),-Math.sin(phi)*Math.cos(this.heading),Math.cos(phi)),distance);
    this.input.lookAt(target);this.input.updateMatrixWorld();
    this.sync();
  }
  sync(target=this.target){
    this.target.copy(target);
    const offset=this.input.position.clone().sub(target),radius=offset.length();
    if(radius>0){
      this.distance=radius;
      this.heading=Math.atan2(offset.x,-offset.y);
      const phi=Math.atan2(Math.hypot(offset.x,offset.y),offset.z);
      // OrbitControls uses acos for its safe-pole input; allow its floating-point
      // rounding band so horizontal motion cannot flicker between zero and EPS.
      this.inclination=phi<=POLE_EPS*1.01?0:Math.PI-phi<=POLE_EPS*1.01?Math.PI:phi;
    }
    const t=this.heading,p=this.inclination;
    const normal=new THREE.Vector3(Math.sin(p)*Math.sin(t),-Math.sin(p)*Math.cos(t),Math.cos(p));
    const right=new THREE.Vector3(Math.cos(t),Math.sin(t),0);
    const up=new THREE.Vector3().crossVectors(normal,right);
    this.output.copy(this.input);
    this.output.position.copy(target).addScaledVector(normal,this.distance);
    this.output.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(right,up,normal));
    this.output.up.set(0,0,1);
    this.output.updateMatrixWorld();
  }
}
