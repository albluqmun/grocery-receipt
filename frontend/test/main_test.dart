import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:grocery_receipt/main.dart';

void main() {
  testWidgets('renders the search screen as the initial route', (tester) async {
    await tester.pumpWidget(const ProviderScope(child: GroceryReceiptApp()));
    await tester.pump();

    expect(find.text('Grocery Receipt'), findsOneWidget);
    expect(find.text('Escribe para buscar productos.'), findsOneWidget);
  });
}
