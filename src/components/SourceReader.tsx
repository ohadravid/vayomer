import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";
import { getLanguageFromI18n } from "../lib/language";
import { loadSourceChapter, loadSourceIndex } from "../lib/sourceData";
import {
  buildReaderHref,
  buildReaderPath,
  getOrderedSourceIndexBooks,
  getReaderNeighbors,
  type SourceChapterPayload,
  type SourceIndexBook,
} from "../lib/sourceReader";

function useSourceIndex() {
  const [indexBooks, setIndexBooks] = useState<SourceIndexBook[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void loadSourceIndex()
      .then((payload) => {
        if (cancelled) return;
        setIndexBooks(getOrderedSourceIndexBooks(payload.books ?? []));
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

function useSourceChapter(bookSlug: string | undefined, chapter: number | null) {
  const [chapterPayload, setChapterPayload] = useState<SourceChapterPayload | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!bookSlug || chapter === null) {
      setChapterPayload(null);
      setFailed(false);
      return;
    }

    let cancelled = false;
    setChapterPayload(null);
    setFailed(false);

    void loadSourceChapter(bookSlug, chapter)
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
  }, [bookSlug, chapter]);

  useEffect(() => {
    if (!chapterPayload || typeof window === "undefined") return;
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
  }, [chapterPayload]);

  return { chapterPayload, failed };
}

function chapterNumbers(book: SourceIndexBook): number[] {
  return Array.from({ length: book.chapter_count }, (_, index) => index + 1);
}

function ReaderLoading() {
  const { t } = useTranslation();
  return <section className="card reader-card">{t("reader.loading")}</section>;
}

function ReaderNotFound() {
  const { t } = useTranslation();
  return <section className="card reader-card">{t("reader.notFound")}</section>;
}

function useReaderLang() {
  const { i18n } = useTranslation();
  return getLanguageFromI18n(i18n);
}

export function ReadBooksPage() {
  const { indexBooks, failed } = useSourceIndex();
  const lang = useReaderLang();

  if (failed) return <ReaderNotFound />;
  if (!indexBooks) return <ReaderLoading />;

  return (
    <section className="card reader-card">
      <div className="reader-list" id="readerBookList">
        {indexBooks.map((book) => (
          <Link key={book.slug} className="reader-list-link" to={buildReaderHref({ lang, bookSlug: book.slug })}>
            <span className="reader-book-he" lang="he" dir="rtl">
              {book.he}
            </span>
            <span className="reader-book-en">{book.en}</span>
          </Link>
        ))}
      </div>
    </section>
  );
}

export function ReadBookPage() {
  const { t } = useTranslation();
  const { bookSlug } = useParams();
  const { indexBooks, failed } = useSourceIndex();
  const lang = useReaderLang();

  if (failed) return <ReaderNotFound />;
  if (!indexBooks) return <ReaderLoading />;

  const currentBook = indexBooks.find((book) => book.slug === bookSlug);
  if (!currentBook) return <ReaderNotFound />;

  return (
    <section className="card reader-card">
      <div className="reader-topline">
        <h2 className="reader-heading">
          <span lang="he" dir="rtl">
            {currentBook.he}
          </span>
          <span>{currentBook.en}</span>
        </h2>
        <Link className="reader-back-link" to={buildReaderPath()}>
          {t("reader.allBooks")}
        </Link>
      </div>

      <div className="reader-chapter-grid" id="readerChapterList">
        {chapterNumbers(currentBook).map((chapter) => (
          <Link
            key={chapter}
            className="reader-chapter-link"
            to={buildReaderHref({ lang, bookSlug: currentBook.slug, chapter })}
          >
            {t("reader.chapterLabel", { chapter })}
          </Link>
        ))}
      </div>
    </section>
  );
}

export function ReadChapterPage() {
  const { t } = useTranslation();
  const { bookSlug, chapter: chapterParam } = useParams();
  const chapter = chapterParam ? Number.parseInt(chapterParam, 10) : Number.NaN;
  const chapterNumber = Number.isInteger(chapter) && chapter > 0 ? chapter : null;
  const { indexBooks, failed: indexFailed } = useSourceIndex();
  const { chapterPayload, failed: chapterFailed } = useSourceChapter(bookSlug, chapterNumber);
  const lang = useReaderLang();

  const currentBook = useMemo(
    () => (indexBooks && bookSlug ? indexBooks.find((book) => book.slug === bookSlug) : undefined),
    [bookSlug, indexBooks]
  );

  const neighbors = useMemo(
    () => (indexBooks && bookSlug && chapterNumber ? getReaderNeighbors(indexBooks, bookSlug, chapterNumber) : { previous: null, next: null }),
    [bookSlug, chapterNumber, indexBooks]
  );

  if (indexFailed || chapterFailed) return <ReaderNotFound />;
  if (!indexBooks || !chapterPayload) return <ReaderLoading />;
  if (!currentBook || chapterNumber === null) return <ReaderNotFound />;

  return (
    <section className="card reader-card">
      <div className="reader-topline">
        <h2 className="reader-heading">
          <span lang="he" dir="rtl">
            {chapterPayload.book_he}
          </span>
          <span>{chapterPayload.book}</span>
          <span className="reader-heading-chapter">{t("reader.chapterLabel", { chapter: chapterPayload.chapter })}</span>
        </h2>
        <Link className="reader-back-link" to={buildReaderHref({ lang, bookSlug: chapterPayload.slug })}>
          {t("reader.backToChapters")}
        </Link>
      </div>

      <div className="reader-chapter-nav">
        {neighbors.previous ? (
          <Link
            className="reader-nav-link"
            to={buildReaderHref({ lang, bookSlug: neighbors.previous.bookSlug, chapter: neighbors.previous.chapter })}
          >
            {t("reader.previousChapter")}
          </Link>
        ) : (
          <span className="reader-nav-link disabled">{t("reader.previousChapter")}</span>
        )}
        {neighbors.next ? (
          <Link
            className="reader-nav-link"
            to={buildReaderHref({ lang, bookSlug: neighbors.next.bookSlug, chapter: neighbors.next.chapter })}
          >
            {t("reader.nextChapter")}
          </Link>
        ) : (
          <span className="reader-nav-link disabled">{t("reader.nextChapter")}</span>
        )}
      </div>

      <div className="reader-verse-list" id="readerVerseList">
        {chapterPayload.verses.map((verse) => {
          const verseHref = buildReaderHref({
            lang,
            bookSlug: chapterPayload.slug,
            chapter: chapterPayload.chapter,
            verse: verse.verse,
          });

          return (
            <article className="reader-verse" id={`v${verse.verse}`} key={verse.verse}>
              <a className="reader-verse-num" href={verseHref}>
                {verse.verse}
              </a>
              <div className="reader-verse-text reader-verse-text-he" lang="he" dir="rtl">
                {verse.he}
              </div>
              <div className="reader-verse-text reader-verse-text-en" lang="en" dir="ltr">
                {verse.en}
              </div>
            </article>
          );
        })}
      </div>

      <div className="reader-chapter-nav">
        {neighbors.previous ? (
          <Link
            className="reader-nav-link"
            to={buildReaderHref({ lang, bookSlug: neighbors.previous.bookSlug, chapter: neighbors.previous.chapter })}
          >
            {t("reader.previousChapter")}
          </Link>
        ) : (
          <span className="reader-nav-link disabled">{t("reader.previousChapter")}</span>
        )}
        {neighbors.next ? (
          <Link
            className="reader-nav-link"
            to={buildReaderHref({ lang, bookSlug: neighbors.next.bookSlug, chapter: neighbors.next.chapter })}
          >
            {t("reader.nextChapter")}
          </Link>
        ) : (
          <span className="reader-nav-link disabled">{t("reader.nextChapter")}</span>
        )}
      </div>
    </section>
  );
}
