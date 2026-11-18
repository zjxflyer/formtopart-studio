/** A visible preview also permits saving when a browser suppresses data-URL downloads. */
export function exportCanvasImage(canvas:HTMLCanvasElement,filename:string){
 const src=canvas.toDataURL('image/png');const link=document.createElement('a');link.download=filename;link.href=src;link.click();
 document.querySelector('[data-view-export]')?.remove();
 const image=document.createElement('img');image.src=src;image.alt='Exported 3D view / 导出的三维视图';image.dataset.viewExport=filename;
 image.style.cssText='position:fixed;right:10px;bottom:10px;width:230px;max-width:50vw;background:white;border:2px solid #608484;z-index:100';
 image.title='Exported PNG preview; click to close / 导出PNG预览，点击关闭';image.onclick=()=>image.remove();document.body.append(image);
}
