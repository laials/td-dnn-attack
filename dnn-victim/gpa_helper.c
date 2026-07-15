/*
 * gpa_helper.c
 *
 * Translates a userspace virtual address to its guest physical address (GPA)
 * using /proc/self/pagemap. Compiled inside the TD guest and linked as a
 * shared library used by all victim Python scripts.
 *
 * Build:
 *   gcc -O2 -shared -fPIC -o libgpa_helper.so gpa_helper.c
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <unistd.h>
#include <fcntl.h>

#define PAGEMAP_ENTRY_SIZE 8
#define PAGE_SHIFT         12
#define PAGE_SIZE          (1UL << PAGE_SHIFT)
#define PFN_MASK           ((1ULL << 55) - 1)

/*
 * virt_to_phys - translate a virtual address to a physical (guest) address.
 *
 * Reads /proc/self/pagemap to find the page frame number (PFN) backing the
 * virtual address, then reconstructs the physical address by combining the
 * PFN with the page offset.
 *
 * Returns the GPA on success, or 0 on failure.
 */
unsigned long virt_to_phys(void *addr) {
    unsigned long vaddr = (unsigned long)addr;
    unsigned long page_offset = vaddr % PAGE_SIZE;
    unsigned long pfn_index   = vaddr / PAGE_SIZE;

    int fd = open("/proc/self/pagemap", O_RDONLY);
    if (fd < 0) {
        perror("open /proc/self/pagemap");
        return 0;
    }

    uint64_t entry = 0;
    off_t offset = (off_t)(pfn_index * PAGEMAP_ENTRY_SIZE);

    if (lseek(fd, offset, SEEK_SET) == (off_t)-1) {
        perror("lseek pagemap");
        close(fd);
        return 0;
    }

    ssize_t bytes_read = read(fd, &entry, PAGEMAP_ENTRY_SIZE);
    close(fd);

    if (bytes_read != PAGEMAP_ENTRY_SIZE) {
        fprintf(stderr, "pagemap read failed for VA 0x%lx\n", vaddr);
        return 0;
    }

    /* Bit 63: page present. Bits 54:0: page frame number. */
    if (!(entry & (1ULL << 63))) {
        fprintf(stderr, "page not present for VA 0x%lx\n", vaddr);
        return 0;
    }

    unsigned long pfn = entry & PFN_MASK;
    return (pfn << PAGE_SHIFT) | page_offset;
}