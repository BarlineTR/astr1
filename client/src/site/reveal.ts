/**
 * Kaydırdıkça beliren parçalar.
 *
 * Bir kere görünen bir daha gizlenmez: ekranda yukarı aşağı gezinirken kartların
 * tekrar tekrar belirip kaybolması, sayfayı okunur olmaktan çıkarıyor.
 */
export function observeReveals(targets: HTMLElement[], reducedMotion: boolean): void {
  if (reducedMotion || !("IntersectionObserver" in window)) {
    for (const target of targets) target.classList.add("is-visible");
    return;
  }

  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      }
    },
    { threshold: 0.15, rootMargin: "0px 0px -8% 0px" },
  );

  for (const target of targets) observer.observe(target);
}
