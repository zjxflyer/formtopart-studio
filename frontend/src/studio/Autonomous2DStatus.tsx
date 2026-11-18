import { t } from './i18n';
import type { Autonomous2DReceipt } from './types';
import './autonomous-2d.css';

export function isUnclassified2DFallback(receipt?: Autonomous2DReceipt | null) {
  return receipt?.group_cycles?.latest_cycle?.metadata?.phase === 'unclassified_source_fallback';
}

export function isUndrawn2D(receipt?: Autonomous2DReceipt | null) {
  return !!receipt && !receipt.accepted && (receipt.view_count === 0 || isUnclassified2DFallback(receipt) || receipt.failed_stage === 'grouping_native_sources');
}

export function Autonomous2DStatus({ receipt }: { receipt?: Autonomous2DReceipt | null }) {
  if (!receipt) return null;
  const sourceFallback = isUnclassified2DFallback(receipt);
  const stoppedBeforeDrawing = isUndrawn2D(receipt);
  const cyclesUsed = sourceFallback && receipt.cycle_count <= 1 ? 0 : receipt.cycle_count;
  return <details className={`autonomous-2d-status ${receipt.accepted ? 'ready' : 'needs_review'}`} open={!receipt.accepted}>
    <summary><strong>{receipt.accepted ? t('2D checks complete', '二维检查完成') : stoppedBeforeDrawing ? t('2D stopped before drawing', '二维任务在绘图前停止') : t('2D needs review', '二维需要复核')}</strong>
      <span>{sourceFallback ? t(`${receipt.view_count} unclassified source views`, `${receipt.view_count} 个未分类原图视图`) : t(`${receipt.view_count} drawing views`, `${receipt.view_count} 张图纸`)} · {sourceFallback && receipt.cycle_count > 1
        ? t(`${receipt.cycle_count} of ${receipt.max_cycles} cycle slots used`, `已占用 ${receipt.cycle_count}/${receipt.max_cycles} 个循环名额`)
        : t(`${cyclesUsed} of ${receipt.max_cycles} drawing cycles started`, `已启动 ${cyclesUsed}/${receipt.max_cycles} 轮绘图`)}</span></summary>
    <p>{receipt.accepted
      ? t('The app created and checked these drawings against the uploaded source. Review the result before saving.', '应用已依据上传原图完成绘图和检查，请核对成果后保存。')
      : stoppedBeforeDrawing
        ? t('This run produced no drawings. The Customer PDF is still available. For a new attempt, use Drawing scope to focus on one room or cabinet.', '本次任务未生成图纸。仍可查看客户 PDF。再次尝试时，可在「图纸范围」中指定一个房间或柜体。')
        : t('The app kept the drawing candidate and its review notes. Resolve the listed issues before saving or continuing to 3D.', '应用已保留候选图纸及复核记录。保存或继续三维前，请先处理所列问题。')}</p>
    {sourceFallback && <p>{t('These source previews can still contain the original textures.', '这些原图预览可能仍含原有材质纹理。')}</p>}
    <p>{t('Studio runs up to two drawing cycles. An automatic second cycle can start after a check requests changes and enough processing capacity remains.', 'Studio 最多运行两轮绘图。第一轮检查要求修改且剩余处理额度充足时，应用可以自动启动第二轮。')}</p>
    {!!receipt.issues?.length && <ul>{receipt.issues.slice(0, 12).map((issue, index) => <li key={index}>{issue}</li>)}</ul>}
    <small>{receipt.request_count}/{receipt.max_requests} {t('assistant requests', '次助手请求')} · {t('Source observations remain unchanged', '原始观测值保持不变')}</small>
  </details>;
}
