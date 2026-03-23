/**
 * GalleryView — Responsive grid layout showing all candidate feeds.
 *
 * Supports pagination for large numbers of candidates (>12 per page).
 */
import React from 'react';
import { Users, ChevronLeft, ChevronRight } from 'lucide-react';
import CandidateCard from './CandidateCard';

const ITEMS_PER_PAGE = 12;

export default function GalleryView({
  candidates,       // { [candidateIndex]: { cameraTrack, screenTrack, uidCam, uidScreen } }
  selectedCandidate, // candidateIndex | null
  onSelectCandidate, // (candidateIndex) => void
}) {
  const [page, setPage] = React.useState(0);

  const candidateEntries = Object.entries(candidates).sort(
    ([a], [b]) => Number(a) - Number(b)
  );
  const totalPages = Math.ceil(candidateEntries.length / ITEMS_PER_PAGE);
  const pageEntries = candidateEntries.slice(
    page * ITEMS_PER_PAGE,
    (page + 1) * ITEMS_PER_PAGE
  );

  // Auto-adjust grid columns based on candidate count
  const getGridCols = () => {
    const count = pageEntries.length;
    if (count <= 1) return 'grid-cols-1';
    if (count <= 2) return 'grid-cols-1 md:grid-cols-2';
    if (count <= 4) return 'grid-cols-1 md:grid-cols-2';
    if (count <= 6) return 'grid-cols-2 md:grid-cols-3';
    if (count <= 9) return 'grid-cols-2 md:grid-cols-3 lg:grid-cols-3';
    return 'grid-cols-2 md:grid-cols-3 lg:grid-cols-4';
  };

  if (candidateEntries.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-gray-500 py-20">
        <div className="w-20 h-20 rounded-full bg-gray-800/50 flex items-center justify-center mb-4">
          <Users size={32} className="text-gray-600" />
        </div>
        <h3 className="text-lg font-medium text-gray-400 mb-1">No candidates connected</h3>
        <p className="text-sm text-gray-600">Waiting for candidates to join the channel...</p>
        <div className="mt-4 flex items-center space-x-2">
          <div className="w-2 h-2 rounded-full bg-primary-400 animate-pulse" />
          <span className="text-xs text-gray-500">Listening for connections</span>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col">
      {/* Grid */}
      <div className={`grid ${getGridCols()} gap-4 p-4 flex-1 auto-rows-fr`}>
        {pageEntries.map(([candidateIndex, data]) => (
          <CandidateCard
            key={candidateIndex}
            candidateIndex={candidateIndex}
            cameraTrack={data.cameraTrack}
            screenTrack={data.screenTrack}
            onClick={() => onSelectCandidate(candidateIndex)}
            isSelected={selectedCandidate === candidateIndex}
          />
        ))}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center space-x-4 py-3 border-t border-white/5">
          <button
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0}
            className="p-2 rounded-lg bg-white/5 text-white hover:bg-white/10 disabled:opacity-30 disabled:cursor-not-allowed transition"
          >
            <ChevronLeft size={16} />
          </button>
          <span className="text-sm text-gray-400">
            Page {page + 1} of {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
            disabled={page >= totalPages - 1}
            className="p-2 rounded-lg bg-white/5 text-white hover:bg-white/10 disabled:opacity-30 disabled:cursor-not-allowed transition"
          >
            <ChevronRight size={16} />
          </button>
        </div>
      )}
    </div>
  );
}
