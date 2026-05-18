package com.musubi.eurio.ml.bench

/**
 * Snapshot of the guided bench protocol's state. Owned by the
 * `ScanViewModel` and consumed by `BenchProtocolOverlay`.
 *
 * `currentIndex == cells.size` means the protocol walked through every
 * cell ; the overlay shows a completion banner and the operator can
 * close it.
 */
data class BenchProtocolState(
    val cells: List<BenchProtocol.Cell>,
    val currentIndex: Int,
    val perCellStatus: List<CellStatus>,
) {
    enum class CellStatus { PENDING, IN_PROGRESS, DONE, SKIPPED }

    val currentCell: BenchProtocol.Cell? get() = cells.getOrNull(currentIndex)
    val currentStatus: CellStatus?
        get() = perCellStatus.getOrNull(currentIndex)

    val totalCells: Int get() = cells.size
    val doneCount: Int get() = perCellStatus.count { it == CellStatus.DONE }
    val skippedCount: Int get() = perCellStatus.count { it == CellStatus.SKIPPED }
    val isComplete: Boolean get() = currentIndex >= cells.size

    fun withStatus(index: Int, status: CellStatus): BenchProtocolState = copy(
        perCellStatus = perCellStatus.toMutableList().also { it[index] = status },
    )

    companion object {
        fun fresh(cells: List<BenchProtocol.Cell>): BenchProtocolState = BenchProtocolState(
            cells = cells,
            currentIndex = 0,
            perCellStatus = List(cells.size) { CellStatus.PENDING },
        )
    }
}
