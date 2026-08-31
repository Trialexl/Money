import { beforeEach, describe, expect, it, vi } from "vitest"

const { post } = vi.hoisted(() => ({ post: vi.fn() }))
vi.mock("@/lib/api", () => ({ default: { post } }))

import { AiService, type AiAssistantHistoryMessage } from "./ai-service"

describe("assistant history transport", () => {
  beforeEach(() => {
    post.mockReset()
    post.mockResolvedValue({ data: { status: "info", reply_text: "Ответ" } })
  })

  it("resends a previous screenshot with a text-only clarification", async () => {
    const image = new File(["bank-image"], "bank.png", { type: "image/png" })
    await AiService.execute({
      mode: "agent", conversation: true, text: "Создай эти операции",
      history: [
        { role: "user", content: "Сбер, расходы Путешествия", image },
        { role: "assistant", content: "Уточните дату" },
      ],
    })
    const body = post.mock.calls[0][1] as FormData
    expect(body).toBeInstanceOf(FormData)
    expect(body.get("image")).toBeNull()
    expect(body.get("text")).toBe("Создай эти операции")
    expect(body.getAll("history_images")).toEqual([image])
    expect(JSON.parse(body.get("history") as string)).toEqual([
      { role: "user", content: "Сбер, расходы Путешествия", image_index: 0 },
      { role: "assistant", content: "Уточните дату" },
    ])
  })

  it("bounds history and keeps only the latest three historical images", async () => {
    const history: AiAssistantHistoryMessage[] = Array.from({ length: 24 }, (_, index) => ({
      role: "user", content: String(index),
      image: new File([String(index)], `${index}.png`, { type: "image/png" }),
    }))
    await AiService.execute({ mode: "agent", text: "Продолжи", history })
    const body = post.mock.calls[0][1] as FormData
    const messages = JSON.parse(body.get("history") as string)
    expect(messages).toHaveLength(20)
    expect(body.getAll("history_images")).toHaveLength(3)
    expect(messages.filter((item: { image_index?: number }) => item.image_index !== undefined))
      .toEqual([
        { role: "user", content: "21", image_index: 0 },
        { role: "user", content: "22", image_index: 1 },
        { role: "user", content: "23", image_index: 2 },
      ])
  })

  it("keeps text requests as JSON and does not resend agent images in classic mode", async () => {
    await AiService.execute({ mode: "classic", text: "Остатки", history: [{
      role: "user", content: "Банк", image: new File(["x"], "bank.png"),
    }] })
    expect(post.mock.calls[0][1]).toMatchObject({
      mode: "classic", history: [{ role: "user", content: "Банк" }],
    })
  })
})
