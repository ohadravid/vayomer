import { describe, expect, it } from "vitest";
import { matchRoutes } from "react-router-dom";
import { APP_ROUTE_OBJECTS } from "./App";

function matchedPaths(pathname: string): Array<string | undefined> {
  return (matchRoutes(APP_ROUTE_OBJECTS, pathname) ?? []).map((match) => match.route.path);
}

describe("APP_ROUTE_OBJECTS", () => {
  it("matches the canonical game route", () => {
    expect(matchedPaths("/")).toEqual([undefined, undefined]);
  });

  it("matches the about and example routes", () => {
    expect(matchedPaths("/about")).toEqual([undefined, "about"]);
    expect(matchedPaths("/example")).toEqual([undefined, "example"]);
  });

  it("matches the reader routes", () => {
    expect(matchedPaths("/read")).toEqual([undefined, "read"]);
    expect(matchedPaths("/read/exodus")).toEqual([undefined, "read/:bookSlug"]);
    expect(matchedPaths("/read/exodus/33")).toEqual([undefined, "read/:bookSlug/:chapter"]);
  });
});
