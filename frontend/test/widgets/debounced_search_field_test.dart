import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:grocery_receipt/widgets/debounced_search_field.dart';

void main() {
  testWidgets('debounces onChanged callbacks', (tester) async {
    final values = <String>[];

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: DebouncedSearchField(
            debounce: const Duration(milliseconds: 100),
            onChanged: values.add,
          ),
        ),
      ),
    );

    await tester.enterText(find.byType(TextField), 'l');
    await tester.pump(const Duration(milliseconds: 50));
    await tester.enterText(find.byType(TextField), 'le');
    await tester.pump(const Duration(milliseconds: 50));
    await tester.enterText(find.byType(TextField), 'leche');

    expect(values, isEmpty);

    await tester.pump(const Duration(milliseconds: 150));

    expect(values, ['leche']);
  });

  testWidgets('cancels pending debounce on dispose', (tester) async {
    final values = <String>[];

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: DebouncedSearchField(
            debounce: const Duration(milliseconds: 100),
            onChanged: values.add,
          ),
        ),
      ),
    );

    await tester.enterText(find.byType(TextField), 'leche');
    await tester.pumpWidget(const MaterialApp(home: Scaffold()));
    await tester.pump(const Duration(milliseconds: 150));

    expect(values, isEmpty);
  });
}
