export function LoadingState() {
  return (
    <main className="shell">
      <section className="empty-panel">
        <h2>加载中</h2>
        <p>正在读取 ARC 数据。</p>
      </section>
    </main>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <main className="shell">
      <section className="empty-panel error">
        <h2>无法打开</h2>
        <p>{message}</p>
      </section>
    </main>
  );
}

export function MissingParams({ message }: { message: string }) {
  return (
    <main className="shell">
      <section className="empty-panel error">
        <h2>链接参数不完整</h2>
        <p>{message}</p>
      </section>
    </main>
  );
}
