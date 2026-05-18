package com.musubi.eurio.ml.trigger

/**
 * Fires once when the [ConsensusBuffer] settles on a new locked class.
 *
 * Mirrors the existing "fiche pièce affichée" trigger, so the best-frame
 * selection happens at the same moment the user would otherwise see the
 * acceptance card. The trade-off is that ArcFace already needs to be running
 * — so we don't gain latency, only the *quality* of the captured frame.
 *
 * Re-fires when the consensus class changes (different coin scanned). The
 * scan ViewModel calls [reset] on `returnToIdle`, which clears the
 * `firedForConsensus` marker so the same class can re-fire after a real
 * dismiss + re-detect cycle.
 */
class ArcfaceConsensusTrigger : TriggerStrategy {

    override val name: String = "arcface_consensus"

    private var firedForConsensus: String? = null

    override fun observe(context: FrameContext): TriggerEvent? {
        val locked = context.consensusLockedClass ?: return null
        if (firedForConsensus == locked) return null
        firedForConsensus = locked
        return TriggerEvent.Fire(
            reason = "consensus $locked",
            bufferSnapshot = context.buffer,
        )
    }

    override fun reset() {
        firedForConsensus = null
    }
}
