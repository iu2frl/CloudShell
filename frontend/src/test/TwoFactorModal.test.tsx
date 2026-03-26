import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { TwoFactorModal } from "../components/TwoFactorModal";

const get2FAStatusMock = vi.fn();
const setup2FAMock = vi.fn();

vi.mock("../api/client", () => ({
  get2FAStatus: (...args: unknown[]) => get2FAStatusMock(...args),
  setup2FA: (...args: unknown[]) => setup2FAMock(...args),
  enable2FA: vi.fn(),
  disable2FA: vi.fn(),
}));

describe("TwoFactorModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    get2FAStatusMock.mockResolvedValue({ enabled: false });
  });

  it("shows setup error in idle state when enabling 2FA fails", async () => {
    setup2FAMock.mockRejectedValue(new Error("Rate limit exceeded"));

    render(<TwoFactorModal onClose={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Two-factor authentication is disabled")).toBeInTheDocument();
    });

    await userEvent.click(screen.getByRole("button", { name: "Enable 2FA" }));

    await waitFor(() => {
      expect(screen.getByText("Error: Rate limit exceeded")).toBeInTheDocument();
    });
  });
});
