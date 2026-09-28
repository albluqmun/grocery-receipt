import 'package:go_router/go_router.dart';

import 'screens/product_screen.dart';
import 'screens/search_screen.dart';

final appRouter = GoRouter(
  routes: [
    GoRoute(path: '/', builder: (ctx, state) => const SearchScreen()),
    GoRoute(
      path: '/product/:id',
      builder: (ctx, state) => ProductScreen(productId: state.pathParameters['id']!),
    ),
  ],
);
