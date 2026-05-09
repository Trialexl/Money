import { createElement } from "react"
import { render, screen, waitFor } from "@testing-library/react"
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
  useActiveCashFlowItemsQueryMock,
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
  useActiveCashFlowItemsQueryMock: vi.fn(),
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
  useActiveCashFlowItemsQuery: (...args: any[]) => useActiveCashFlowItemsQueryMock(...args),
  useWalletBalanceQuery: (...args: any[]) => useWalletBalanceQueryMock(...args),
}))

vi.mock("@/components/shared/planning-graphics-panel", () => ({
  PlanningGraphicsPanel: () => null,
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
import { SearchableSelect } from "@/components/shared/searchable-select"
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
    useActiveCashFlowItemsQueryMock.mockReturnValue({
      data: [
        {
          id: "item-1",
          name: "Budget item",
          code: null,
          deleted: false,
        },
      ],
      isLoading: false,
      isError: false,
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

  it("keeps ranked cash flow options first when searching", async () => {
    const user = userEvent.setup()
    render(
      createElement(SearchableSelect, {
        value: "unselected",
        onValueChange: vi.fn(),
        placeholder: "Выбери статью",
        searchPlaceholder: "Найти статью",
        options: [
          { value: "unselected", label: "Не выбрано" },
          { value: "transport", label: "Проезд", rank: 2 },
          { value: "food", label: "Продукты", rank: 9 },
          { value: "rent", label: "Аренда", rank: 100 },
        ],
      })
    )

    await user.click(screen.getByRole("combobox"))
    await user.type(screen.getByPlaceholderText("Найти статью"), "про")

    await waitFor(() => {
      const labels = screen.getAllByRole("option").map((option) => option.textContent)
      expect(labels[0]).toContain("Продукты")
      expect(labels[1]).toContain("Проезд")
    })
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

    await user.click(screen.getByRole("button", { name: /Создать перевод/ }))

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

    await user.click(screen.getByRole("button", { name: /Создать перевод/ }))

    expect(await screen.findByText("Недостаточно средств. Сейчас на кошельке доступно 100.")).toBeInTheDocument()
    expect(createTransferMock).not.toHaveBeenCalled()
  })

  it("allows editing a transfer when the current document amount already reduced the source balance", async () => {
    updateTransferMock.mockResolvedValue({
      id: "transfer-3",
    })

    const user = userEvent.setup()
    render(
      createElement(TransferForm, {
        isEdit: true,
        transfer: {
          id: "transfer-3",
          number: "TR-003",
          date: "2026-03-10",
          amount: 150,
          wallet_from: "wallet-1",
          wallet_to: "wallet-2",
        },
      })
    )

    await waitFor(() => {
      expect(useWalletBalanceQueryMock).toHaveBeenCalledWith("wallet-1", "2026-03-10")
    })
    await user.click(screen.getByRole("button", { name: /Сохранить/ }))

    await waitFor(() => {
      expect(updateTransferMock).toHaveBeenCalledWith("transfer-3", {
        amount: 150,
        date: "2026-03-10",
        description: undefined,
        wallet_from: "wallet-1",
        wallet_to: "wallet-2",
        cash_flow_item: undefined,
        include_in_budget: false,
      })
    })
    expect(screen.queryByText(/Недостаточно средств/)).not.toBeInTheDocument()
  })

  it("does not add back the edited transfer amount outside the selected balance date", async () => {
    const user = userEvent.setup()
    render(
      createElement(TransferForm, {
        isEdit: true,
        transfer: {
          id: "transfer-5",
          number: "TR-005",
          date: "2026-03-10",
          amount: 150,
          wallet_from: "wallet-1",
          wallet_to: "wallet-2",
        },
      })
    )

    await user.clear(screen.getByLabelText("Дата перевода"))
    await user.type(screen.getByLabelText("Дата перевода"), "2026-03-09")
    await user.click(screen.getByRole("button", { name: /Сохранить/ }))

    expect(await screen.findByText("Недостаточно средств. Сейчас на кошельке доступно 100.")).toBeInTheDocument()
    expect(updateTransferMock).not.toHaveBeenCalled()
  })

  it("saves a budget transfer with the selected cash flow item", async () => {
    updateTransferMock.mockResolvedValue({
      id: "transfer-4",
    })

    const user = userEvent.setup()
    render(
      createElement(TransferForm, {
        isEdit: true,
        transfer: {
          id: "transfer-4",
          number: "TR-004",
          date: "2026-03-10",
          amount: 50,
          wallet_from: "wallet-1",
          wallet_to: "wallet-2",
          include_in_budget: true,
          cash_flow_item: "item-1",
          cash_flow_item_name: "Budget item",
        },
      })
    )

    expect(screen.getByText("Статья движения")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: /Сохранить/ }))

    await waitFor(() => {
      expect(updateTransferMock).toHaveBeenCalledWith("transfer-4", {
        amount: 50,
        date: "2026-03-10",
        description: undefined,
        wallet_from: "wallet-1",
        wallet_to: "wallet-2",
        cash_flow_item: "item-1",
        include_in_budget: true,
      })
    })
  })

  it("saves transfer amount from an arithmetic expression", async () => {
    createTransferMock.mockResolvedValue({
      id: "transfer-6",
    })
    useWalletBalanceQueryMock.mockReturnValue({
      data: { balance: 3000 },
      isLoading: false,
    })

    const user = userEvent.setup()
    render(
      createElement(TransferForm, {
        transfer: {
          id: "transfer-6",
          number: "TR-006",
          date: "2026-03-10",
          amount: 50,
          wallet_from: "wallet-1",
          wallet_to: "wallet-2",
        },
      })
    )

    await user.clear(screen.getByLabelText("Сумма"))
    await user.type(screen.getByLabelText("Сумма"), "6000-4000")
    await user.click(screen.getByRole("button", { name: /Создать перевод/ }))

    await waitFor(() => {
      expect(createTransferMock).toHaveBeenCalledWith(
        expect.objectContaining({
          amount: 2000,
        })
      )
    })
  })
})
