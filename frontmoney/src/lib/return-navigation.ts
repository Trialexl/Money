type QueryLike = { toString: () => string } | null | undefined

export function buildReturnToHref(pathname: string, searchParams: QueryLike) {
  const params = new URLSearchParams(searchParams?.toString() ?? "")
  params.delete("highlight")

  const query = params.toString()
  return query ? `${pathname}?${query}` : pathname
}

export function withReturnToHref(href: string, returnToHref: string) {
  const params = new URLSearchParams()
  params.set("return_to", returnToHref)

  return `${href}${href.includes("?") ? "&" : "?"}${params.toString()}`
}

interface ResolveReturnHrefOptions {
  resetPage?: boolean
}

export function resolveReturnHref(
  returnToHref: string | null | undefined,
  fallbackHref: string,
  highlightId?: string | null,
  options: ResolveReturnHrefOptions = {}
) {
  const url = new URL(returnToHref || fallbackHref, "https://local.invalid")

  if (options.resetPage) {
    url.searchParams.delete("page")
  }

  if (highlightId) {
    url.searchParams.set("highlight", highlightId)
  } else {
    url.searchParams.delete("highlight")
  }

  return `${url.pathname}${url.search}`
}
