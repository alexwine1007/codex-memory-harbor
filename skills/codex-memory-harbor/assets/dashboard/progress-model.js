/* Pure presentation model; never infers release from verified bytes. */
(function (root) {
  function number(value) { return Number.isFinite(Number(value)) ? Math.max(0, Number(value)) : 0; }
  function state(job, format, translate) {
    const completed = number(job.completed), total = number(job.total);
    const complete = job.status === 'complete' && completed === total;
    const failed = job.status === 'failed';
    const verified = number(job.bytes);
    const released = job.released_bytes ?? job.metrics?.released_bytes;
    let detail = '正在复制与逐项校验，尚未完成的内容保留在本机。';
    if (complete) {
      if (released == null) detail = `已验证 ${format(verified)}；空间释放情况请查看回执。`;
      else if (number(released) === 0) detail = `已验证 ${format(verified)}；本次未移除本地副本。`;
      else detail = `已验证 ${format(verified)}；本次移除 ${format(number(released))} 的本地文件。`;
    }
    if (failed) detail = '操作已停止，未通过校验的内容保留在本机。';
    const title = complete ? '停泊完成' : failed ? '操作已停止' : '正在安全停泊';
    if (translate) detail = translate(failed ? 'errorHint' : complete ? released == null ? 'releaseUnknown' : number(released) === 0 ? 'releaseZero' : 'releaseDone' : 'progressRunning', {size:format(verified),released:format(number(released))});
    return {
      complete, failed, completed, total, verified,
      percent: complete ? 100 : Math.min(99, total ? completed / total * 100 : 0),
      title: translate ? translate(complete ? 'complete' : failed ? 'failed' : 'docking') : title, detail,
    };
  }
  const api = { state };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.HarborProgress = api;
})(typeof window !== 'undefined' ? window : this);
