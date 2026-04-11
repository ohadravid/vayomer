import type { AnchorHTMLAttributes, MouseEvent } from "react";

type Props = AnchorHTMLAttributes<HTMLAnchorElement> & {
  href: string;
};

function isPlainLeftClick(event: MouseEvent<HTMLAnchorElement>): boolean {
  return event.button === 0 && !event.metaKey && !event.altKey && !event.ctrlKey && !event.shiftKey;
}

function dispatchPopState(): void {
  if (typeof window === "undefined") return;
  if (typeof PopStateEvent === "function") {
    window.dispatchEvent(new PopStateEvent("popstate"));
    return;
  }
  window.dispatchEvent(new Event("popstate"));
}

function scrollToHashTarget(hash: string): void {
  if (typeof window === "undefined" || !hash) return;
  const targetId = decodeURIComponent(hash.replace(/^#/, ""));
  const scroll = () => {
    const target = document.getElementById(targetId);
    if (target && typeof target.scrollIntoView === "function") {
      target.scrollIntoView();
    }
  };
  if (typeof window.requestAnimationFrame === "function") {
    window.requestAnimationFrame(scroll);
    return;
  }
  scroll();
}

export function navigateWithinApp(href: string): void {
  if (typeof window === "undefined") return;
  const current = new URL(window.location.href);
  const next = new URL(href, current.origin);
  if (next.origin !== current.origin) {
    window.location.assign(next.toString());
    return;
  }

  const currentLocation = `${current.pathname}${current.search}${current.hash}`;
  const nextLocation = `${next.pathname}${next.search}${next.hash}`;
  if (currentLocation === nextLocation) return;

  const hashOnlyChange = current.pathname === next.pathname && current.search === next.search && current.hash !== next.hash;
  if (hashOnlyChange) {
    window.location.hash = next.hash;
    return;
  }

  window.history.pushState(window.history.state, "", nextLocation);
  if (next.hash) {
    scrollToHashTarget(next.hash);
  } else {
    try {
      window.scrollTo(0, 0);
    } catch {
      // Ignore scroll API failures in tests.
    }
  }
  dispatchPopState();
}

export function InternalLink({ href, onClick, target, rel, ...props }: Props) {
  const handleClick = (event: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(event);
    if (event.defaultPrevented) return;
    if (!isPlainLeftClick(event)) return;
    if (target && target !== "_self") return;
    if ((event.currentTarget.getAttribute("download") ?? "").length > 0) return;

    event.preventDefault();
    navigateWithinApp(href);
  };

  return <a {...props} href={href} onClick={handleClick} rel={rel} target={target} />;
}
