import * as THREE from 'three';
import type { SpatialScene } from './types';

/** Display finishes only. Textures never change geometry, board sizes or BOM data. */
export type FinishStyle = { kind: 'wood' | 'stone' | 'metal' | 'glass' | 'solid'; roughness: number; metalness: number };

export function finishStyle(scene: SpatialScene, material: string): FinishStyle {
  const snapshot = scene.project.material_snapshots?.find(item => `CATALOG_${item.snapshot_id}` === material);
  const value = snapshot?.variant;
  const text = [material, value?.code, value?.name, value?.category, value?.substrate, value?.finish].filter(Boolean).join(' ');
  if (/metal|brass|steel|chrome|^MT\b/i.test(text)) return { kind: 'metal', roughness: .29, metalness: .78 };
  if (/glass|^GL\b/i.test(text)) return { kind: 'glass', roughness: .16, metalness: .08 };
  if (/stone|quartz|marble|calacatta|travertine|^ST\d/i.test(text)) return { kind: 'stone', roughness: .31, metalness: .03 };
  if (/lacquer|paint|solid.?color|matte.?finish/i.test(text)) return { kind: 'solid', roughness: .57, metalness: .02 };
  if (/wood|oak|walnut|veneer|timber|^WD\d/i.test(text)) return { kind: 'wood', roughness: .68, metalness: 0 };
  return { kind: 'solid', roughness: .8, metalness: 0 };
}

export function finishTexture(kind: FinishStyle['kind']): THREE.CanvasTexture | null {
  if (kind !== 'wood' && kind !== 'stone') return null;
  const canvas = document.createElement('canvas'); canvas.width = canvas.height = 256;
  const context = canvas.getContext('2d');
  if (!context) return null;
  context.fillStyle = '#ffffff'; context.fillRect(0, 0, 256, 256);
  // Fixed analytic patterns keep the complete presentation reproducible/offline.
  if (kind === 'wood') {
    for (let x = 0; x < 256; x++) {
      const shade = Math.round(238 + 10 * Math.sin(x * .43) + 5 * Math.sin(x * 1.91));
      context.strokeStyle = `rgba(${shade},${shade},${shade},.5)`;
      context.beginPath();
      for (let y = 0; y <= 256; y += 4) {
        const px = x + 1.9 * Math.sin(y / 57 + x / 19);
        if (y === 0) context.moveTo(px, y); else context.lineTo(px, y);
      }
      context.stroke();
    }
  } else {
    for (let k = -3; k < 7; k++) {
      context.strokeStyle = 'rgba(115,112,105,.13)'; context.lineWidth = k % 2 ? .7 : 1.5;
      context.beginPath();
      for (let y = -5; y <= 261; y += 3) {
        const x = k * 67 + y * .45 + 13 * Math.sin(y / 38 + k) + 4 * Math.sin(y / 11 + k);
        if (y === -5) context.moveTo(x, y); else context.lineTo(x, y);
      }
      context.stroke();
    }
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
  texture.anisotropy = 4;
  return texture;
}

export function finishUV(geometry: THREE.BufferGeometry) {
  const position = geometry.getAttribute('position');
  geometry.computeBoundingBox(); const bounds = geometry.boundingBox!;
  const span = bounds.getSize(new THREE.Vector3());
  const axes: Array<'x' | 'y' | 'z'> = ['x', 'y', 'z'];
  axes.sort((a, b) => span[b] - span[a]);
  const vertices = Array.from({ length: position.count }, (_, index) => new THREE.Vector3().fromBufferAttribute(position, index));
  const uv = vertices.flatMap(v => [v[axes[0]] / 1100, v[axes[1]] / 1100]);
  geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
}
