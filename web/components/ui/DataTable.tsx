'use client';

import React from 'react';
import { motion } from 'framer-motion';
import { C, R, F, SP } from '../../src/theme';
import { staggerContainer, fadeUp } from '../../src/animations';
import { Skeleton } from './Skeleton';
import { EmptyState } from './EmptyState';

export interface DataTableColumn {
  key: string;
  label: string;
  align?: 'left' | 'right' | 'center';
  render?: (value: any, row: any) => React.ReactNode;
}

export interface DataTableProps {
  columns: DataTableColumn[];
  data: any[];
  onRowClick?: (row: any) => void;
  loading?: boolean;
  emptyMessage?: string;
  maxHeight?: number;
}

export function DataTable({
  columns,
  data,
  onRowClick,
  loading = false,
  emptyMessage = 'No data available',
  maxHeight,
}: DataTableProps) {
  if (!loading && data.length === 0) {
    return <EmptyState title={emptyMessage} />;
  }

  return (
    <div
      style={{
        overflowX: 'auto',
        overflowY: maxHeight ? 'auto' : undefined,
        maxHeight: maxHeight ?? undefined,
        borderRadius: R.lg,
        border: `1px solid ${C.border}`,
      }}
    >
      <table
        style={{
          width: '100%',
          borderCollapse: 'collapse',
          fontSize: F.sm,
        }}
      >
        <thead>
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                style={{
                  padding: `${SP[2]}px ${SP[3]}px`,
                  textAlign: col.align ?? 'left',
                  fontSize: F.xs,
                  fontWeight: 600,
                  textTransform: 'uppercase',
                  letterSpacing: '0.06em',
                  color: C.muted,
                  borderBottom: `1px solid ${C.border}`,
                  position: 'sticky',
                  top: 0,
                  background: C.card,
                  zIndex: 1,
                  whiteSpace: 'nowrap',
                }}
              >
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <motion.tbody
          variants={staggerContainer}
          initial="hidden"
          animate="show"
        >
          {loading
            ? Array.from({ length: 5 }).map((_, i) => (
                <tr key={`skel-${i}`}>
                  {columns.map((col) => (
                    <td
                      key={col.key}
                      style={{
                        padding: `${SP[2]}px ${SP[3]}px`,
                        borderBottom: `1px solid ${C.faint}`,
                      }}
                    >
                      <Skeleton w="70%" h={14} />
                    </td>
                  ))}
                </tr>
              ))
            : data.map((row, i) => (
                <motion.tr
                  key={i}
                  variants={fadeUp}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  style={{
                    cursor: onRowClick ? 'pointer' : undefined,
                    transition: 'background 0.15s ease',
                  }}
                  onMouseEnter={(e) => {
                    (e.currentTarget as HTMLElement).style.background = C.surfaceHover;
                  }}
                  onMouseLeave={(e) => {
                    (e.currentTarget as HTMLElement).style.background = 'transparent';
                  }}
                >
                  {columns.map((col) => {
                    const val = row[col.key];
                    const isNumber = typeof val === 'number';
                    return (
                      <td
                        key={col.key}
                        style={{
                          padding: `${SP[2]}px ${SP[3]}px`,
                          textAlign: col.align ?? 'left',
                          borderBottom: `1px solid ${C.faint}`,
                          color: C.textSub,
                          fontVariantNumeric: isNumber ? 'tabular-nums' : undefined,
                          fontFamily: isNumber ? "'JetBrains Mono', monospace" : undefined,
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {col.render ? col.render(val, row) : (val ?? '\u2014')}
                      </td>
                    );
                  })}
                </motion.tr>
              ))}
        </motion.tbody>
      </table>
    </div>
  );
}

export default DataTable;
