import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../models/price_history_entry.dart';

class PriceTable extends StatelessWidget {
  final List<PriceHistoryEntry> entries;
  const PriceTable({super.key, required this.entries});

  @override
  Widget build(BuildContext context) {
    if (entries.isEmpty) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 24),
        child: Text('Sin histórico de compras.'),
      );
    }
    final dateFmt = DateFormat('yyyy-MM-dd');
    final priceFmt = NumberFormat.currency(locale: 'es_ES', symbol: '€');
    return DataTable(
      columns: const [
        DataColumn(label: Text('Fecha')),
        DataColumn(label: Text('Supermercado')),
        DataColumn(label: Text('Precio unitario'), numeric: true),
      ],
      rows: entries
          .map(
            (e) => DataRow(cells: [
              DataCell(Text(dateFmt.format(e.date))),
              DataCell(Text(e.supermarketName)),
              DataCell(Text(priceFmt.format(e.unitPrice))),
            ]),
          )
          .toList(),
    );
  }
}
