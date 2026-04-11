import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { loadSourceChapter, loadSourceIndex } from "../lib/sourceData";
import { buildReaderHref, buildReaderPath, type ReaderRoute, type SourceChapterPayload, type SourceIndexBook } from "../lib/sourceReader";
import type { Lang } from "../types";
import { InternalLink } from "./InternalLink";

type Props = {
  route: ReaderRoute;
  lang: Lang;
};

function sortChapterNumbers(chapters: readonly number[]): number[] {
  return [...chapters].sort((left, right) => left - right);
}

function useSourceIndex() {
  const [indexBooks, setIndexBooks] = useState<SourceIndexBook[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void loadSourceIndex()
      .then((payload) => {
        if (cancelled) return;
        setIndexBooks(payload.books ?? []);
        setFailed(false);
      })
      .catch(() => {
        if (cancelled) return;
        setIndexBooks(null);
        setFailed(true);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return { indexBooks, failed };
}

function useSourceChapter(route: ReaderRoute) {
  const [chapterPayload, setChapterPayload] = useState<SourceChapterPayload | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (route.kind !== "read-chapter") {
      setChapterPayload(null);
      setFailed(false);
      return;
    }

    let cancelled = false;
    setChapterPayload(null);
    setFailed(false);

    void loadSourceChapter(route.bookSlug, route.chapter)
      .then((payload) => {
        if (cancelled) return;
        setChapterPayload(payload);
      })
      .catch(() => {
        if (cancelled) return;
        setFailed(true);
      });

    return () => {
      cancelled = true;
    };
  }, [route]);

  useEffect(() => {
    if (route.kind !== "read-chapter" || !chapterPayload || typeof window === "undefined") return;
    const hash = window.location.hash;
    if (!hash) return;
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
  }, [chapterPayload, route]);

  return { chapterPayload, failed };
}

export function SourceReader({ route, lang }: Props) {
  const { t } = useTranslation();
  const { indexBooks, failed: indexFailed } = useSourceIndex();
  const { chapterPayload, failed: chapterFailed } = useSourceChapter(route);

  if (route.kind === "read-not-found") {
    return <section className="card reader-card">{t("reader.notFound")}</section>;
  }

  const currentBook = useMemo(() => {
    if (!indexBooks || (route.kind !== "read-book" && route.kind !== "read-chapter")) return null;
    return indexBooks.find((book) => book.slug === route.bookSlug) ?? null;
  }, [indexBooks, route]);

  if (indexFailed) {
    return <section className="card reader-card">{t("reader.notFound")}</section>;
  }

  if (!indexBooks) {
    return <section className="card reader-card">{t("reader.loading")}</section>;
  }

  if ((route.kind === "read-book" || route.kind === "read-chapter") && !currentBook) {
    return <section className="card reader-card">{t("reader.notFound")}</section>;
  }

  if (route.kind === "read-books") {
    return (
      <section className="card reader-card">
        <div className="reader-list" id="readerBookList">
          {indexBooks.map((book) => (
            <InternalLink
              key={book.slug}
              className="reader-list-link"
              href={buildReaderHref({ lang, bookSlug: book.slug })}
            >
              <span className="reader-book-en">{book.en}</span>
              <span className="reader-book-he" lang="he" dir="rtl">
                {book.he}
              </span>
            </InternalLink>
          ))}
        </div>
      </section>
    );
  }

  if (route.kind === "read-book" && currentBook) {
    const chapters = sortChapterNumbers(currentBook.chapters);
    return (
      <section className="card reader-card">
        <div className="reader-topline">
          <h2 className="reader-heading">
            <span>{currentBook.en}</span>
            <span lang="he" dir="rtl">
              {currentBook.he}
            </span>
          </h2>
          <InternalLink className="reader-back-link" href={buildReaderPath()}>
            {t("reader.allBooks")}
          </InternalLink>
        </div>

        <div className="reader-chapter-grid" id="readerChapterList">
          {chapters.map((chapter) => (
            <InternalLink
              key={chapter}
              className="reader-chapter-link"
              href={buildReaderHref({ lang, bookSlug: currentBook.slug, chapter })}
            >
              {t("reader.chapterLabel", { chapter })}
            </InternalLink>
          ))}
        </div>
      </section>
    );
  }

  if (!chapterPayload || chapterFailed) {
    return <section className="card reader-card">{chapterFailed ? t("reader.notFound") : t("reader.loading")}</section>;
  }

  return (
    <section className="card reader-card">
      <div className="reader-topline">
        <h2 className="reader-heading">
          <span>{chapterPayload.book}</span>
          <span lang="he" dir="rtl">
            {chapterPayload.book_he}
          </span>
          <span className="reader-heading-chapter">{t("reader.chapterLabel", { chapter: chapterPayload.chapter })}</span>
        </h2>
        <InternalLink className="reader-back-link" href={buildReaderHref({ lang, bookSlug: chapterPayload.slug })}>
          {t("reader.backToChapters")}
        </InternalLink>
      </div>
      <div className="reader-verse-list" id="readerVerseList">
        {chapterPayload.verses.map((verse) => (
          <article className="reader-verse" id={`v${verse.verse}`} key={verse.verse}>
            <div className="reader-verse-num">{verse.verse}</div>
            <div className="reader-verse-text reader-verse-text-en" lang="en" dir="ltr">
              {verse.en}
            </div>
            <div className="reader-verse-text reader-verse-text-he" lang="he" dir="rtl">
              {verse.he}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
