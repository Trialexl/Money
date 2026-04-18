import { createElement } from "react"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

const {
  pushMock,
  invalidateQueriesMock,
  mutationSpy,
  createWalletMock,
  updateWalletMock,
  createTransferMock,
  updateTransferMock,
  useActiveWalletsQueryMock,
  useWalletBalanceQueryMock,
} = vi.hoisted(() => ({
  pushMock: vi.fn(),
  invalidateQueriesMock: vi.fn().mockResolvedValue(undefined),
  mutationSpy: vi.fn(),
  createWalletMock: vi.fn(),
  updateWalletMock: vi.fn(),
  createTransferMock: vi.fn(),
  updateTransferMock: vi.fn(),
  useActiveWalletsQueryMock: vi.fn(),
  useWalletBalanceQueryMock: vi.fn(),
}))

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: unknown; href: string }) => createElement("a", { href }, children),
}))

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: pushMock,
  }),
  useSearchParams: () => new URLSearchParams(),
}))

vi.mock("@tanstack/react-query", () => ({
  useQuery: () => ({
    data: [],
    isLoading: false,
    isError: false,
  }),
  useQueryClient: () => ({
    invalidateQueries: invalidateQueriesMock,
  }),
  useMutation: (options: any) => {
    mutationSpy.mockImplementation(options.mutationFn)

    return {
      mutateAsync: async () => {
        const result = await options.mutationFn()
        if (options.onSuccess) {
          await options.onSuccess(result)
        }
        return result
      },
      isPending: false,
      error: null,
    }
  },
}))

vi.mock("@/hooks/use-reference-data", () => ({
  useActiveWalletsQuery: (...args: any[]) => useActiveWalletsQueryMock(...args),
  useWalletBalanceQuery: (...args: any[]) => useWalletBalanceQueryMock(...args),
}))

vi.mock("@/services/wallet-service", () => ({
  WalletService: {
    createWallet: (...args: any[]) => createWalletMock(...args),
    updateWallet: (...args: any[]) => updateWalletMock(...args),
  },
}))

vi.mock("@/services/financial-operations-service", () => ({
  TransferService: {
    createTransfer: (...args: any[]) => createTransferMock(...args),
    updateTransfer: (...args: any[]) => updateTransferMock(...args),
  },
}))

import TransferForm from "@/components/shared/transfer-form"
import WalletForm from "@/components/shared/wallet-form"

describe("shared forms", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    invalidateQueriesMock.mockResolvedValue(undefined)
    useActiveWalletsQueryMock.mockReturnValue({
      data: [
        {
          id: "wallet-1",
          name: "Main wallet",
        },
        {
          id: "wallet-2",
          name: "Reserve wallet",
        },
      ],
      isLoading: false,
      isError: false,
    })
    useWalletBalanceQueryMock.mockReturnValue({
      data: { balance: 100 },
      isLoading: false,
    })
  })

  it("creates a wallet with trimmed payload and redirects to the detail page", async () => {
    createWalletMock.mockResolvedValue({
      id: "wallet-99",
    })

    const user = userEvent.setup()
    render(createElement(WalletForm))

    await user.type(screen.getByLabelText("Название"), "  Main wallet  ")
    await user.click(screen.getByRole("button", { name: "Создать кошелек" }))

    expect(createWalletMock).toHaveBeenCalledWith({
      name: "Main wallet",
      hidden: false,
    })
    expect(invalidateQueriesMock).toHaveBeenCalledWith({ queryKey: ["wallets"] })
    expect(invalidateQueriesMock).toHaveBeenCalledWith({ queryKey: ["dashboard-overview"] })
    expect(pushMock).toHaveBeenCalledWith("/wallets/wallet-99")
  })

  it("blocks a transfer when source and destination wallets are the same", async () => {
    const user = userEvent.setup()
    render(
      createElement(TransferForm, {
        transfer: {
          id: "transfer-1",
          number: "TR-001",
          date: "2026-03-10",
          amount: 50,
          wallet_from: "wallet-1",
          wallet_to: "wallet-1",
        },
      })
    )

    await user.click(screen.getByRole("button", { name: "Создать перевод" }))

    expect(await screen.findByText("Кошелек отправления и кошелек получения должны отличаться.")).toBeInTheDocument()
    expect(createTransferMock).not.toHaveBeenCalled()
  })

  it("blocks a transfer when the requested amount exceeds the available balance", async () => {
    const user = userEvent.setup()
    render(
      createElement(TransferForm, {
        transfer: {
          id: "transfer-2",
          number: "TR-002",
          date: "2026-03-10",
          amount: 150,
          wallet_from: "wallet-1",
          wallet_to: "wallet-2",
        },
      })
    )

    await user.click(screen.getByRole("button", { name: "Создать перевод" }))

    expect(await screen.findByText("Недостаточно средств. Сейчас на кошельке доступно 100.")).toBeInTheDocument()
    expect(createTransferMock).not.toHaveBeenCalled()
  })
})
