import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:grocery_receipt/models/price_history_entry.dart';
import 'package:grocery_receipt/widgets/price_table.dart';

void main() {
  Widget wrap(Widget child) => MaterialApp(home: Scaffold(body: child));

  testWidgets('shows empty state when there are no entries', (tester) async {
    await tester.pumpWidget(wrap(const PriceTable(entries: [])));

    expect(find.text('Sin histórico de compras.'), findsOneWidget);
    expect(find.byType(DataTable), findsNothing);
  });

  testWidgets('renders a row per entry with formatted date and price', (tester) async {
    final entries = [
      PriceHistoryEntry(
        date: DateTime(2026, 4, 10),
        supermarketName: 'Mercadona',
        unitPrice: 1.35,
      ),
    ];

    await tester.pumpWidget(wrap(PriceTable(entries: entries)));

    expect(find.text('2026-04-10'), findsOneWidget);
    expect(find.text('Mercadona'), findsOneWidget);
    expect(find.byType(DataTable), findsOneWidget);
  });
}
